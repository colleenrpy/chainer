import unittest

import numpy

import chainer
from chainer.backends import cuda
from chainer import functions
from chainer import gradient_check
from chainer import testing
from chainer.testing import attr
from chainer.testing import backend


@testing.parameterize(
    {'dtype': numpy.float16, 'ratio': 0.1},
    {'dtype': numpy.float32, 'ratio': 0.3},
    {'dtype': numpy.float64, 'ratio': 0.5},
    {'dtype': numpy.float64, 'ratio': 0.0},
)
@backend.inject_backend_tests(
    ['test_forward', 'test_backward', 'test_double_backward',
     'test_immutable'],
    # CPU tests
    testing.product({
        'use_cuda': [False],
        'use_ideep': ['never', 'always'],
    })
    # GPU tests
    + testing.product({
        'use_cuda': [True],
        'use_cudnn': ['never', 'always'],
    }))
class TestDropout(unittest.TestCase):

    def setUp(self):
        dtype = self.dtype
        x = numpy.random.uniform(-1, 1, (2, 3)).astype(dtype)
        gy = numpy.random.uniform(-1, 1, (2, 3)).astype(dtype)
        ggx = numpy.random.uniform(-1, 1, (2, 3)).astype(dtype)

        self.inputs = [x]
        self.grad_outputs = [gy]
        self.grad_grad_inputs = [ggx]

        self.check_backward_options = {'dtype': numpy.float64}
        self.check_double_backward_options = {'dtype': numpy.float64}
        if self.dtype == numpy.float16:
            self.check_backward_options = {
                'dtype': numpy.float64, 'atol': 1e-3, 'rtol': 1e-2}
            self.check_double_backward_options = {
                'dtype': numpy.float64, 'atol': 1e-3, 'rtol': 1e-2}

    def forward_cpu(self, inputs, ratio, mask):
        x, = inputs
        if ratio == 0.0:
            y_expected = x
        else:
            y_expected = x * mask
        return y_expected,

    def check_forward(self, inputs, backend_config):
        if backend_config.use_cuda:
            inputs = cuda.to_gpu(inputs)

        with backend_config:
            y = functions.dropout(*(inputs + [self.ratio]))

        if backend_config.use_cudnn == 'always':
            if self.ratio == 0.0:
                y_expected, = inputs
                testing.assert_allclose(y_expected, y.data)
            else:
                self.assertTrue(cuda.cupy.all(inputs[0] != y.data))
        else:
            # In the calculation of expected results,
            # the mask used in test forward computation is reused.
            mask = y.creator.mask
            y_expected, = self.forward_cpu(inputs, self.ratio, mask)

            assert y.data.dtype == self.dtype
            testing.assert_allclose(y_expected, y.data)

    def test_forward(self, backend_config):
        self.check_forward(self.inputs, backend_config)

    def check_backward(self, inputs, grad_outputs, backend_config):
        if backend_config.use_cuda:
            inputs = cuda.to_gpu(inputs)
            grad_outputs = cuda.to_gpu(grad_outputs)

        # Instantiate the function class directly in order to reuse the mask,
        # because f will be called repeatedly.
        dropout = functions.Dropout(self.ratio)

        def f(*inputs):
            return dropout.apply(inputs)

        with backend_config:
            gradient_check.check_backward(
                f, inputs, grad_outputs, **self.check_backward_options)

    def test_backward(self, backend_config):
        self.check_backward(self.inputs, self.grad_outputs, backend_config)

    def check_double_backward(
            self, inputs, grad_outputs, grad_grad_inputs, backend_config):
        if backend_config.use_cuda:
            inputs = cuda.to_gpu(inputs)
            grad_outputs = cuda.to_gpu(grad_outputs)
            grad_grad_inputs = cuda.to_gpu(grad_grad_inputs)

        # Instantiate the function class directly in order to reuse the mask,
        # because f will be called repeatedly.
        dropout = functions.Dropout(self.ratio)

        def f(*inputs):
            y, = dropout.apply(inputs)
            return y * y,

        with backend_config:
            gradient_check.check_double_backward(
                f, inputs, grad_outputs, grad_grad_inputs,
                **self.check_double_backward_options)

    def test_double_backward(self, backend_config):
        self.check_double_backward(
            self.inputs, self.grad_outputs, self.grad_grad_inputs,
            backend_config)

    def check_immutable(self, inputs, backend_config):
        if backend_config.use_cuda:
            inputs = cuda.to_gpu(inputs)

        with backend_config:
            dropout = functions.Dropout(0.5)
            y1, = dropout.apply(inputs)
            y2, = dropout.apply(inputs)
        testing.assert_allclose(y1.data, y2.data)

    def test_immutable(self, backend_config):
        self.check_immutable(self.inputs, backend_config)


@testing.parameterize(*testing.product({
    'specify_mask': [True, False],
    'train': [True, False],
}))
class TestDropoutMask(unittest.TestCase):

    def setUp(self):
        self.x = numpy.random.uniform(-1, 1, (2, 3)).astype(numpy.float32)
        self.mask = (numpy.random.uniform(-1, 1, (2, 3)) > 0).astype(
            numpy.float32)

    def _check(self):
        mask = self.mask if self.specify_mask else None
        with chainer.using_config('train', self.train):
            out, out_mask = functions.dropout(
                self.x, 0.5, mask=mask, return_mask=True)

        if self.train:
            assert isinstance(out_mask, type(out.array))
            if mask is None:
                assert out_mask.shape == out.array.shape
            else:
                assert out_mask is mask
        else:
            assert out_mask is None

        with chainer.using_config('train', self.train):
            out2 = functions.dropout(self.x, 0.5, mask=out_mask)
        testing.assert_allclose(out.array, out2.array)

    def test_cpu(self):
        with chainer.using_config('use_ideep', 'never'):
            self._check()

    @attr.ideep
    def test_cpu_ideep(self):
        with chainer.using_config('use_ideep', 'always'):
            self._check()

    @attr.gpu
    def test_gpu(self):
        self.x = cuda.to_gpu(self.x)
        self.mask = cuda.to_gpu(self.mask)
        self._check()


testing.run_module(__name__, __file__)
