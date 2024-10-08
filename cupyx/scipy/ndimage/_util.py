import operator
import warnings
from collections.abc import Iterable

import cupy
from cupy import AxisError


def _is_integer_output(output, input):
    if output is None:
        return input.dtype.kind in 'iu'
    elif isinstance(output, cupy.ndarray):
        return output.dtype.kind in 'iu'
    return cupy.dtype(output).kind in 'iu'


def _check_cval(mode, cval, integer_output):
    if mode == 'constant' and integer_output and not cupy.isfinite(cval):
        raise NotImplementedError("Non-finite cval is not supported for "
                                  "outputs with integer dtype.")


def _init_weights_dtype(input):
    """Initialize filter weights based on the input array.

    This helper is only used during initialization of some internal filters
    like prewitt and sobel to avoid costly double-precision computation.
    """
    if input.dtype.kind == "c":
        return cupy.promote_types(input.real.dtype, cupy.complex64)
    return cupy.promote_types(input.real.dtype, cupy.float32)


def _get_weights_dtype(input, weights):
    if weights.dtype.kind == "c" or input.dtype.kind == "c":
        return cupy.promote_types(input.real.dtype, cupy.complex64)
    elif weights.dtype.kind in 'iub':
        # convert integer dtype weights to double as in SciPy
        return cupy.float64
    return cupy.promote_types(input.real.dtype, cupy.float32)


def _get_output(output, input, shape=None, complex_output=False):
    shape = input.shape if shape is None else shape
    if output is None:
        if complex_output:
            _dtype = cupy.promote_types(input.dtype, cupy.complex64)
        else:
            _dtype = input.dtype
        output = cupy.empty(shape, dtype=_dtype)
    elif isinstance(output, (type, cupy.dtype)):
        if complex_output and cupy.dtype(output).kind != 'c':
            warnings.warn("promoting specified output dtype to complex")
            output = cupy.promote_types(output, cupy.complex64)
        output = cupy.empty(shape, dtype=output)
    elif isinstance(output, str):
        output = cupy.dtype(output)
        if complex_output and output.kind != 'c':
            raise RuntimeError("output must have complex dtype")
        output = cupy.empty(shape, dtype=output)
    elif output.shape != shape:
        raise RuntimeError("output shape not correct")
    elif complex_output and output.dtype.kind != 'c':
        raise RuntimeError("output must have complex dtype")
    return output


def _fix_sequence_arg(arg, ndim, name, conv=lambda x: x):
    if isinstance(arg, str):
        return [conv(arg)] * ndim
    try:
        arg = iter(arg)
    except TypeError:
        return [conv(arg)] * ndim
    lst = [conv(x) for x in arg]
    if len(lst) != ndim:
        msg = "{} must have length equal to input rank".format(name)
        raise RuntimeError(msg)
    return lst


def _check_origin(origin, width):
    origin = int(origin)
    if (width // 2 + origin < 0) or (width // 2 + origin >= width):
        raise ValueError('invalid origin')
    return origin


def _check_mode(mode):
    if mode not in ('reflect', 'constant', 'nearest', 'mirror', 'wrap',
                    'grid-mirror', 'grid-wrap', 'grid-reflect'):
        msg = f'boundary mode not supported (actual: {mode})'
        raise RuntimeError(msg)
    return mode


def _check_axes(axes, ndim):
    if axes is None:
        return tuple(range(ndim))
    elif cupy.isscalar(axes):
        axes = (operator.index(axes),)
    elif isinstance(axes, Iterable):
        for ax in axes:
            axes = tuple(operator.index(ax) for ax in axes)
            if ax < -ndim or ax > ndim - 1:
                raise AxisError(f"specified axis: {ax} is out of range")
        axes = tuple(ax % ndim if ax < 0 else ax for ax in axes)
    else:
        message = "axes must be an integer, iterable of integers, or None"
        raise ValueError(message)
    if len(tuple(set(axes))) != len(axes):
        raise ValueError("axes must be unique")
    return axes


def _get_inttype(input):
    # The integer type to use for indices in the input array
    # The indices actually use byte positions and we can't just use
    # input.nbytes since that won't tell us the number of bytes between the
    # first and last elements when the array is non-contiguous
    nbytes = sum((x-1)*abs(stride) for x, stride in
                 zip(input.shape, input.strides)) + input.dtype.itemsize
    return 'int' if nbytes < (1 << 31) else 'ptrdiff_t'


def _generate_boundary_condition_ops(mode, ix, xsize, int_t="int",
                                     float_ix=False):
    min_func = "fmin" if float_ix else "min"
    max_func = "fmax" if float_ix else "max"
    if mode in ['reflect', 'grid-mirror']:
        ops = '''
        if ({ix} < 0) {{
            {ix} = - 1 -{ix};
        }}
        {ix} %= {xsize} * 2;
        {ix} = {min}({ix}, 2 * {xsize} - 1 - {ix});'''.format(
            ix=ix, xsize=xsize, min=min_func)
    elif mode == 'mirror':
        ops = '''
        if ({xsize} == 1) {{
            {ix} = 0;
        }} else {{
            if ({ix} < 0) {{
                {ix} = -{ix};
            }}
            {ix} = 1 + ({ix} - 1) % (({xsize} - 1) * 2);
            {ix} = {min}({ix}, 2 * {xsize} - 2 - {ix});
        }}'''.format(ix=ix, xsize=xsize, min=min_func)
    elif mode == 'nearest':
        ops = '''
        {ix} = {min}({max}(({T}){ix}, ({T})0), ({T})({xsize} - 1));'''.format(
            ix=ix, xsize=xsize, min=min_func, max=max_func,
            # force using 64-bit signed integer for ptrdiff_t,
            # see cupy/cupy#6048
            T=('int' if int_t == 'int' else 'long long'))
    elif mode == 'grid-wrap':
        ops = '''
        {ix} %= {xsize};
        while ({ix} < 0) {{
            {ix} += {xsize};
        }}'''.format(ix=ix, xsize=xsize)
    elif mode == 'wrap':
        ops = '''
        if ({ix} < 0) {{
            {ix} += ({sz} - 1) * (({int_t})(-{ix} / ({sz} - 1)) + 1);
        }} else if ({ix} > ({sz} - 1)) {{
            {ix} -= ({sz} - 1) * ({int_t})({ix} / ({sz} - 1));
        }};'''.format(ix=ix, sz=xsize, int_t=int_t)
    elif mode in ['constant', 'grid-constant']:
        ops = '''
        if (({ix} < 0) || {ix} >= {xsize}) {{
            {ix} = -1;
        }}'''.format(ix=ix, xsize=xsize)
    return ops


def _generate_indices_ops(ndim, int_type, offsets):
    code = '{type} ind_{j} = _i % ysize_{j} - {offset}; _i /= ysize_{j};'
    body = [code.format(type=int_type, j=j, offset=offsets[j])
            for j in range(ndim-1, 0, -1)]
    return '{type} _i = i;\n{body}\n{type} ind_0 = _i - {offset};'.format(
        type=int_type, body='\n'.join(body), offset=offsets[0])
