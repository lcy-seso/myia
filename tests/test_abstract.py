
import pytest
import asyncio

from myia import dtype as ty
from myia.prim import ops as P
from myia.prim.py_implementations import typeof
from myia.abstract import (
    ANYTHING, MyiaTypeError,
    AbstractScalar, AbstractTuple as T, AbstractList as L,
    AbstractJTagged, abstract_union, AbstractError, AbstractFunction,
    InferenceLoop, to_abstract, build_value, amerge,
    Possibilities as _Poss,
    VALUE, TYPE, DEAD, build_type_fn,
    PrimitiveFunction, PartialApplication, VirtualFunction,
    TypedPrimitive, abstract_clone, abstract_clone_async, broaden
)
from myia.utils import SymbolicKeyInstance
from myia.ir import Constant

from .common import Point, to_abstract_test, f32, Ty, af32_of


def U(*opts):
    return abstract_union(opts)


def S(v=ANYTHING, t=None, s=None):
    return AbstractScalar({
        VALUE: v,
        TYPE: t or typeof(v),
    })


def Poss(*things):
    return AbstractScalar({
        VALUE: _Poss(things),
        TYPE: typeof(things[0]),
    })


def test_to_abstract():
    inst = SymbolicKeyInstance(Constant(123), 456)
    expected = AbstractScalar({VALUE: inst, TYPE: ty.SymbolicKeyType})
    assert to_abstract(inst) == expected


def test_build_value():
    assert build_value(S(1)) == 1
    with pytest.raises(ValueError):
        build_value(S(t=ty.Int[64]))
    assert build_value(S(t=ty.Int[64]), default=ANYTHING) is ANYTHING

    assert build_value(T([S(1), S(2)])) == (1, 2)

    loop = InferenceLoop(errtype=Exception)
    p = loop.create_pending(resolve=(lambda: None), priority=(lambda: None))
    with pytest.raises(ValueError):
        assert build_value(S(p)) is p
    assert build_value(S(p), default=ANYTHING) is ANYTHING
    p.set_result(1234)
    assert build_value(S(p)) == 1234

    pt = Point(1, 2)
    assert build_value(to_abstract_test(pt)) == pt


def test_build_type_fn():
    assert build_type_fn(AbstractFunction(PrimitiveFunction('test'))) \
        == ty.Function

    assert build_type_fn(AbstractFunction(PartialApplication(
        VirtualFunction((to_abstract(1), to_abstract(2)), to_abstract(3)),
        (to_abstract(1),)))) == ty.Function[[ty.Int[64]], ty.Int[64]]

    assert build_type_fn(AbstractFunction(TypedPrimitive(
        'test2', (to_abstract(3.0), to_abstract(1)), to_abstract(True)))) \
        == ty.Function[[ty.Float[64], ty.Int[64]], ty.Bool]


def test_merge():
    a = T([S(1), S(t=ty.Int[64])])
    b = T([S(1), S(t=ty.Int[64])])
    c = T([S(t=ty.Int[64]), S(t=ty.Int[64])])

    assert amerge(a, b, loop=None, forced=False) is a
    assert amerge(a, c, loop=None, forced=False) == c
    assert amerge(c, a, loop=None, forced=False) is c

    with pytest.raises(MyiaTypeError):
        amerge(a, c, loop=None, forced=True)

    assert amerge(1, 2, loop=None, forced=False) is ANYTHING
    with pytest.raises(MyiaTypeError):
        assert amerge(1, 2, loop=None, forced=True)

    with pytest.raises(MyiaTypeError):
        assert amerge("hello", "world", loop=None, forced=False)


def test_merge_possibilities():
    a = Poss(1, 2)
    b = Poss(2, 3)
    c = Poss(2)
    assert amerge(a, b,
                  loop=None,
                  forced=False) == Poss(1, 2, 3)
    assert amerge(a, c,
                  loop=None,
                  forced=False) is a

    with pytest.raises(MyiaTypeError):
        amerge(a, b, loop=None, forced=True)

    assert amerge(a, c, loop=None, forced=True) is a


def test_union():
    a = U(S(t=ty.Int[64]), S(t=ty.Int[32]), S(t=ty.Int[16]))
    b = U(S(t=ty.Int[64]), U(S(t=ty.Int[32]), S(t=ty.Int[16])))
    assert a == b

    c = S(t=ty.Int[64])
    d = U(S(t=ty.Int[64]))
    assert c == d

    u = ty.Union[ty.Int[64], ty.Int[32], ty.Int[16]]
    assert build_type_fn(a) == u
    assert repr(u).startswith('Union')  # member order can vary


def test_repr():

    s1 = to_abstract_test(1)
    assert repr(s1) == 'S(VALUE=1, TYPE=Int[64])'

    s2 = to_abstract_test(f32)
    assert repr(s2) == 'S(TYPE=Float[32])'

    t1 = to_abstract_test((1, f32))
    assert repr(t1) == f'T({s1}, {s2})'

    l1 = to_abstract_test([f32])
    assert repr(l1) == f'L({s2})'

    a1 = to_abstract_test(af32_of(4, 5))
    assert repr(a1) == f'A({s2}, SHAPE=(4, 5))'

    p1 = to_abstract_test(Point(1, f32))
    assert repr(p1) == f'*Point(x={s1}, y={s2})'

    j1 = AbstractJTagged(to_abstract_test(1))
    assert repr(j1) == f'J({s1})'

    ty1 = Ty(f32)
    assert repr(ty1) == 'Ty(Float[32])'

    e1 = AbstractError(DEAD)
    assert repr(e1) == 'E(DEAD)'

    f1 = AbstractFunction(P.scalar_mul)
    assert repr(f1) == 'Fn(Possibilities({scalar_mul}))'


@abstract_clone.variant
def upcast(self, x: AbstractScalar, nbits):
    return AbstractScalar({
        VALUE: x.values[VALUE],
        TYPE: ty.Int[nbits],
    })


def test_abstract_clone():
    s1 = S(t=ty.Int[32])
    s2 = S(t=ty.Int[64])
    assert upcast(s1, 64) is s2

    a1 = T([s1, L(s1)])
    assert upcast(a1, 64) is T([s2, L(s2)])


@abstract_clone_async.variant
async def upcast_async(self, x: AbstractScalar):
    return AbstractScalar({
        VALUE: x.values[VALUE],
        TYPE: ty.Int[64],
    })


def test_abstract_clone_async():
    # Coverage test

    async def coro():
        s1 = S(t=ty.Int[32])
        s2 = S(t=ty.Int[64])
        assert (await upcast_async(s1)) is s2

        a1 = T([s1, L(s1)])
        assert (await upcast_async(a1)) is T([s2, L(s2)])

        f1 = AbstractFunction(P.scalar_add, P.scalar_mul)
        assert (await upcast_async(f1)) is f1

        u1 = U(s1, s2)
        assert (await upcast_async(u1)) is s2

    asyncio.run(coro())


def test_broaden():
    # Coverage test

    p = _Poss([1, 2, 3])
    assert broaden(p, None) is p