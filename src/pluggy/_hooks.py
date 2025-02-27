"""
Internal hook annotation, representation and calling machinery.
"""
import inspect
import sys
import warnings
from types import ModuleType
from typing import AbstractSet
from typing import Any
from typing import Callable
from typing import Generator
from typing import List
from typing import Mapping
from typing import Optional
from typing import overload
from typing import Sequence
from typing import Tuple
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union

from ._result import _Result

if TYPE_CHECKING:
    from typing_extensions import TypedDict
    from typing_extensions import Final


_T = TypeVar("_T")
_F = TypeVar("_F", bound=Callable[..., object])
_Namespace = Union[ModuleType, type]
_Plugin = object
_HookExec = Callable[
    [str, Sequence["HookImpl"], Mapping[str, object], bool],
    Union[object, List[object]],
]
_HookImplFunction = Callable[..., Union[_T, Generator[None, _Result[_T], None]]]
if TYPE_CHECKING:

    class _HookSpecOpts(TypedDict):
        firstresult: bool
        historic: bool
        warn_on_impl: Optional[Warning]

    class _HookImplOpts(TypedDict):
        hookwrapper: bool
        optionalhook: bool
        tryfirst: bool
        trylast: bool
        specname: Optional[str]


class HookspecMarker:
    """Decorator for marking functions as hook specifications.

    Instantiate it with a project_name to get a decorator.
    Calling :meth:`PluginManager.add_hookspecs` later will discover all marked
    functions if the :class:`PluginManager` uses the same project_name.
    """

    __slots__ = ("project_name",)

    def __init__(self, project_name: str) -> None:
        self.project_name: "Final" = project_name

    @overload
    def __call__(
        self,
        function: _F,
        firstresult: bool = False,
        historic: bool = False,
        warn_on_impl: Optional[Warning] = None,
    ) -> _F:
        ...

    @overload  # noqa: F811
    def __call__(  # noqa: F811
        self,
        function: None = ...,
        firstresult: bool = ...,
        historic: bool = ...,
        warn_on_impl: Optional[Warning] = ...,
    ) -> Callable[[_F], _F]:
        ...

    def __call__(  # noqa: F811
        self,
        function: Optional[_F] = None,
        firstresult: bool = False,
        historic: bool = False,
        warn_on_impl: Optional[Warning] = None,
    ) -> Union[_F, Callable[[_F], _F]]:
        """If passed a function, directly sets attributes on the function
        which will make it discoverable to :meth:`PluginManager.add_hookspecs`.

        If passed no function, returns a decorator which can be applied to a
        function later using the attributes supplied.

        If ``firstresult`` is ``True``, the 1:N hook call (N being the number of
        registered hook implementation functions) will stop at I<=N when the
        I'th function returns a non-``None`` result.

        If ``historic`` is ``True``, every call to the hook will be memorized
        and replayed on plugins registered after the call was made.
        """

        def setattr_hookspec_opts(func: _F) -> _F:
            if historic and firstresult:
                raise ValueError("cannot have a historic firstresult hook")
            opts: "_HookSpecOpts" = {
                "firstresult": firstresult,
                "historic": historic,
                "warn_on_impl": warn_on_impl,
            }
            setattr(func, self.project_name + "_spec", opts)
            return func

        if function is not None:
            return setattr_hookspec_opts(function)
        else:
            return setattr_hookspec_opts


class HookimplMarker:
    """Decorator for marking functions as hook implementations.

    Instantiate it with a ``project_name`` to get a decorator.
    Calling :meth:`PluginManager.register` later will discover all marked
    functions if the :class:`PluginManager` uses the same project_name.
    """

    __slots__ = ("project_name",)

    def __init__(self, project_name: str) -> None:
        self.project_name: "Final" = project_name

    @overload
    def __call__(
        self,
        function: _F,
        hookwrapper: bool = ...,
        optionalhook: bool = ...,
        tryfirst: bool = ...,
        trylast: bool = ...,
        specname: Optional[str] = ...,
    ) -> _F:
        ...

    @overload  # noqa: F811
    def __call__(  # noqa: F811
        self,
        function: None = ...,
        hookwrapper: bool = ...,
        optionalhook: bool = ...,
        tryfirst: bool = ...,
        trylast: bool = ...,
        specname: Optional[str] = ...,
    ) -> Callable[[_F], _F]:
        ...

    def __call__(  # noqa: F811
        self,
        function: Optional[_F] = None,
        hookwrapper: bool = False,
        optionalhook: bool = False,
        tryfirst: bool = False,
        trylast: bool = False,
        specname: Optional[str] = None,
    ) -> Union[_F, Callable[[_F], _F]]:
        """If passed a function, directly sets attributes on the function
        which will make it discoverable to :meth:`PluginManager.register`.

        If passed no function, returns a decorator which can be applied to a
        function later using the attributes supplied.

        If ``optionalhook`` is ``True``, a missing matching hook specification
        will not result in an error (by default it is an error if no matching
        spec is found).

        If ``tryfirst`` is ``True``, this hook implementation will run as early
        as possible in the chain of N hook implementations for a specification.

        If ``trylast`` is ``True``, this hook implementation will run as late as
        possible in the chain of N hook implementations.

        If ``hookwrapper`` is ``True``, the hook implementations needs to
        execute exactly one ``yield``. The code before the ``yield`` is run
        early before any non-hookwrapper function is run. The code after the
        ``yield`` is run after all non-hookwrapper function have run  The
        ``yield`` receives a :class:`_Result` object representing the exception
        or result outcome of the inner calls (including other hookwrapper
        calls).

        If ``specname`` is provided, it will be used instead of the function
        name when matching this hook implementation to a hook specification
        during registration.
        """

        def setattr_hookimpl_opts(func: _F) -> _F:
            opts: "_HookImplOpts" = {
                "hookwrapper": hookwrapper,
                "optionalhook": optionalhook,
                "tryfirst": tryfirst,
                "trylast": trylast,
                "specname": specname,
            }
            setattr(func, self.project_name + "_impl", opts)
            return func

        if function is None:
            return setattr_hookimpl_opts
        else:
            return setattr_hookimpl_opts(function)


def normalize_hookimpl_opts(opts: "_HookImplOpts") -> None:
    opts.setdefault("tryfirst", False)
    opts.setdefault("trylast", False)
    opts.setdefault("hookwrapper", False)
    opts.setdefault("optionalhook", False)
    opts.setdefault("specname", None)


_PYPY = hasattr(sys, "pypy_version_info")


def varnames(func: object) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Return tuple of positional and keywrord argument names for a function,
    method, class or callable.

    In case of a class, its ``__init__`` method is considered.
    For methods the ``self`` parameter is not included.
    """
    if inspect.isclass(func):
        try:
            func = func.__init__
        except AttributeError:
            return (), ()
    elif not inspect.isroutine(func):  # callable object?
        try:
            func = getattr(func, "__call__", func)
        except Exception:
            return (), ()

    try:
        # func MUST be a function or method here or we won't parse any args.
        sig = inspect.signature(
            func.__func__ if inspect.ismethod(func) else func  # type:ignore[arg-type]
        )
    except TypeError:
        return (), ()

    _valid_param_kinds = (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    _valid_params = {
        name: param
        for name, param in sig.parameters.items()
        if param.kind in _valid_param_kinds
    }
    args = tuple(_valid_params)
    defaults = (
        tuple(
            param.default
            for param in _valid_params.values()
            if param.default is not param.empty
        )
        or None
    )

    if defaults:
        index = -len(defaults)
        args, kwargs = args[:index], tuple(args[index:])
    else:
        kwargs = ()

    # strip any implicit instance arg
    # pypy3 uses "obj" instead of "self" for default dunder methods
    if not _PYPY:
        implicit_names: Tuple[str, ...] = ("self",)
    else:
        implicit_names = ("self", "obj")
    if args:
        qualname: str = getattr(func, "__qualname__", "")
        if inspect.ismethod(func) or ("." in qualname and args[0] in implicit_names):
            args = args[1:]

    return args, kwargs


class _HookRelay:
    """Hook holder object for performing 1:N hook calls where N is the number
    of registered plugins."""

    __slots__ = ("__dict__",)

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> "_HookCaller":
            ...


_CallHistory = List[Tuple[Mapping[str, object], Optional[Callable[[Any], None]]]]


class _HookCaller:
    __slots__ = (
        "name",
        "spec",
        "_hookexec",
        "_hookimpls",
        "_call_history",
    )

    def __init__(
        self,
        name: str,
        hook_execute: _HookExec,
        specmodule_or_class: Optional[_Namespace] = None,
        spec_opts: Optional["_HookSpecOpts"] = None,
    ) -> None:
        self.name: "Final" = name
        self._hookexec: "Final" = hook_execute
        self._hookimpls: "Final[List[HookImpl]]" = []
        self._call_history: Optional[_CallHistory] = None
        self.spec: Optional[HookSpec] = None
        if specmodule_or_class is not None:
            assert spec_opts is not None
            self.set_specification(specmodule_or_class, spec_opts)

    def has_spec(self) -> bool:
        return self.spec is not None

    def set_specification(
        self,
        specmodule_or_class: _Namespace,
        spec_opts: "_HookSpecOpts",
    ) -> None:
        assert not self.has_spec()
        self.spec = HookSpec(specmodule_or_class, self.name, spec_opts)
        if spec_opts.get("historic"):
            self._call_history = []

    def is_historic(self) -> bool:
        return self._call_history is not None

    def _remove_plugin(self, plugin: _Plugin) -> None:
        for i, method in enumerate(self._hookimpls):
            if method.plugin == plugin:
                del self._hookimpls[i]
                return
        raise ValueError(f"plugin {plugin!r} not found")

    def get_hookimpls(self) -> List["HookImpl"]:
        return self._hookimpls.copy()

    def _add_hookimpl(self, hookimpl: "HookImpl") -> None:
        """Add an implementation to the callback chain."""
        for i, method in enumerate(self._hookimpls):
            if method.hookwrapper:
                splitpoint = i
                break
        else:
            splitpoint = len(self._hookimpls)
        if hookimpl.hookwrapper:
            start, end = splitpoint, len(self._hookimpls)
        else:
            start, end = 0, splitpoint

        if hookimpl.trylast:
            self._hookimpls.insert(start, hookimpl)
        elif hookimpl.tryfirst:
            self._hookimpls.insert(end, hookimpl)
        else:
            # find last non-tryfirst method
            i = end - 1
            while i >= start and self._hookimpls[i].tryfirst:
                i -= 1
            self._hookimpls.insert(i + 1, hookimpl)

    def __repr__(self) -> str:
        return f"<_HookCaller {self.name!r}>"

    def _verify_all_args_are_provided(self, kwargs: Mapping[str, object]) -> None:
        # This is written to avoid expensive operations when not needed.
        if self.spec:
            for argname in self.spec.argnames:
                if argname not in kwargs:
                    notincall = ", ".join(
                        repr(argname)
                        for argname in self.spec.argnames
                        # Avoid self.spec.argnames - kwargs.keys() - doesn't preserve order.
                        if argname not in kwargs.keys()
                    )
                    warnings.warn(
                        "Argument(s) {} which are declared in the hookspec "
                        "cannot be found in this hook call".format(notincall),
                        stacklevel=2,
                    )
                    break

    def __call__(self, **kwargs: object) -> Any:
        assert (
            not self.is_historic()
        ), "Cannot directly call a historic hook - use call_historic instead."
        self._verify_all_args_are_provided(kwargs)
        firstresult = self.spec.opts.get("firstresult", False) if self.spec else False
        return self._hookexec(self.name, self._hookimpls, kwargs, firstresult)

    def call_historic(
        self,
        result_callback: Optional[Callable[[Any], None]] = None,
        kwargs: Optional[Mapping[str, object]] = None,
    ) -> None:
        """Call the hook with given ``kwargs`` for all registered plugins and
        for all plugins which will be registered afterwards.

        If ``result_callback`` is provided, it will be called for each
        non-``None`` result obtained from a hook implementation.
        """
        assert self._call_history is not None
        kwargs = kwargs or {}
        self._verify_all_args_are_provided(kwargs)
        self._call_history.append((kwargs, result_callback))
        # Historizing hooks don't return results.
        # Remember firstresult isn't compatible with historic.
        res = self._hookexec(self.name, self._hookimpls, kwargs, False)
        if result_callback is None:
            return
        if isinstance(res, list):
            for x in res:
                result_callback(x)

    def call_extra(
        self, methods: Sequence[Callable[..., object]], kwargs: Mapping[str, object]
    ) -> Any:
        """Call the hook with some additional temporarily participating
        methods using the specified ``kwargs`` as call parameters."""
        assert (
            not self.is_historic()
        ), "Cannot directly call a historic hook - use call_historic instead."
        self._verify_all_args_are_provided(kwargs)
        opts: "_HookImplOpts" = {
            "hookwrapper": False,
            "optionalhook": False,
            "trylast": False,
            "tryfirst": False,
            "specname": None,
        }
        hookimpls = self._hookimpls.copy()
        for method in methods:
            hookimpl = HookImpl(None, "<temp>", method, opts)
            # Find last non-tryfirst nonwrapper method.
            i = len(hookimpls) - 1
            while i >= 0 and hookimpls[i].tryfirst and not hookimpls[i].hookwrapper:
                i -= 1
            hookimpls.insert(i + 1, hookimpl)
        firstresult = self.spec.opts.get("firstresult", False) if self.spec else False
        return self._hookexec(self.name, hookimpls, kwargs, firstresult)

    def _maybe_apply_history(self, method: "HookImpl") -> None:
        """Apply call history to a new hookimpl if it is marked as historic."""
        if self.is_historic():
            assert self._call_history is not None
            for kwargs, result_callback in self._call_history:
                res = self._hookexec(self.name, [method], kwargs, False)
                if res and result_callback is not None:
                    # XXX: remember firstresult isn't compat with historic
                    assert isinstance(res, list)
                    result_callback(res[0])


class _SubsetHookCaller(_HookCaller):
    """A proxy to another HookCaller which manages calls to all registered
    plugins except the ones from remove_plugins."""

    # This class is unusual: in inhertits from `_HookCaller` so all of
    # the *code* runs in the class, but it delegates all underlying *data*
    # to the original HookCaller.
    # `subset_hook_caller` used to be implemented by creating a full-fledged
    # HookCaller, copying all hookimpls from the original. This had problems
    # with memory leaks (#346) and historic calls (#347), which make a proxy
    # approach better.
    # An alternative implementation is to use a `_getattr__`/`__getattribute__`
    # proxy, however that adds more overhead and is more tricky to implement.

    __slots__ = (
        "_orig",
        "_remove_plugins",
        "name",
        "_hookexec",
    )

    def __init__(self, orig: _HookCaller, remove_plugins: AbstractSet[_Plugin]) -> None:
        self._orig = orig
        self._remove_plugins = remove_plugins
        self.name = orig.name  # type: ignore[misc]
        self._hookexec = orig._hookexec  # type: ignore[misc]

    @property  # type: ignore[misc]
    def _hookimpls(self) -> List["HookImpl"]:
        return [
            impl
            for impl in self._orig._hookimpls
            if impl.plugin not in self._remove_plugins
        ]

    @property
    def spec(self) -> Optional["HookSpec"]:  # type: ignore[override]
        return self._orig.spec

    @property
    def _call_history(self) -> Optional[_CallHistory]:  # type: ignore[override]
        return self._orig._call_history

    def __repr__(self) -> str:
        return f"<_SubsetHookCaller {self.name!r}>"


class HookImpl:
    __slots__ = (
        "function",
        "argnames",
        "kwargnames",
        "plugin",
        "opts",
        "plugin_name",
        "hookwrapper",
        "optionalhook",
        "tryfirst",
        "trylast",
    )

    def __init__(
        self,
        plugin: _Plugin,
        plugin_name: str,
        function: _HookImplFunction[object],
        hook_impl_opts: "_HookImplOpts",
    ) -> None:
        self.function: "Final" = function
        self.argnames, self.kwargnames = varnames(self.function)
        self.plugin = plugin
        self.opts = hook_impl_opts
        self.plugin_name = plugin_name
        self.hookwrapper = hook_impl_opts["hookwrapper"]
        self.optionalhook = hook_impl_opts["optionalhook"]
        self.tryfirst = hook_impl_opts["tryfirst"]
        self.trylast = hook_impl_opts["trylast"]

    def __repr__(self) -> str:
        return f"<HookImpl plugin_name={self.plugin_name!r}, plugin={self.plugin!r}>"


class HookSpec:
    __slots__ = (
        "namespace",
        "function",
        "name",
        "argnames",
        "kwargnames",
        "opts",
        "warn_on_impl",
    )

    def __init__(self, namespace: _Namespace, name: str, opts: "_HookSpecOpts") -> None:
        self.namespace = namespace
        self.function: Callable[..., object] = getattr(namespace, name)
        self.name = name
        self.argnames, self.kwargnames = varnames(self.function)
        self.opts = opts
        self.warn_on_impl = opts.get("warn_on_impl")
