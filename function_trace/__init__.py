'''Python lisp-like tracing library.  Prints to stdout a nested
display of function calls with arguments and return values.  Also
prints exceptions when exceptions are thrown.

It works by temporarily replacing all functions/methods within the
listed classes/modules with traced versions.  Then when the 'trace'
block exits, all the original values are restored.

Notes:

* When tracing classes, only the methods defined in that class
are traced, inherited methods are not traced.

* Tracing __repr__ will cause a stack overflow, since this method is
used to print out trace arguments.  The tracer will always skip
tracing this method, even when using `include_hidden`.

* You can change where the trace goes by redefining `tracer`.  It
  should be a function that takes f, *args, **kwargs and calls f with
  the args.  By default it points to `stdout_tracer`.

Usage:

with trace_on([Class1, module1, Class2, module2]):
    module1.function1(arg1, arg2)
    x = new Class1()
    x.method1(arg1, arg2)

'''

from contextlib import contextmanager
from inspect import isroutine

indentchar = "|   "
indent_level = 0


def _name(f):
    return "%s.%s" % (f.__module__, f.__name__)


def stdout_tracer(f, *args, **kwargs):
    global indent_level
    print "%s- %s(%s)" % (indent_level * indentchar, _name(f), ", ".join(map(repr, args)))
    indent_level += 1
    try:
        r = f(*args, **kwargs)
    except Exception as e:
        r = e  # print the exception as the return val
        raise
    finally:
        indent_level -= 1
        print "%s-> %s" % (indent_level * indentchar, repr(r))
    return r

tracer = stdout_tracer


def trace(f):
    # print "Producing traced version of " + f.__name__
    def g(*args, **kwargs):
        return tracer(f, *args, **kwargs)
    return g


@contextmanager
def trace_on(objs, include_hidden=False):
    origs = {}
    for o in objs:
        replacements = {}
        for k in o.__dict__.keys():
            v = o.__dict__[k]
            if isroutine(v) and v.__name__ is not '__repr__' \
               and (include_hidden or
                    not (include_hidden or k.startswith("_"))):
                replacements[k] = v
                # print "Replacing: " + k
                setattr(o, k, trace(v))
        origs[o] = replacements
    # print origs
    try:
        yield
    finally:  # set all the original values back
        for o in objs:
            originals = origs[o]
            for k in originals.keys():
                setattr(o, k, originals[k])
