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
  the args.  By default it points to `trace`.

Usage:

with trace_on([Class1, module1, Class2, module2]):
    module1.function1(arg1, arg2)
    x = new Class1()
    x.method1(arg1, arg2)

'''

from contextlib import contextmanager, closing
from inspect import isclass
import threading
import os

indentchar = "|   "


def _name(f):
    return "%s.%s" % (getattr(f, '__module__', "module"),
                      getattr(f, '__name__', "name"))


class Formatter(object):
    def __init__(self):
        pass

    def format_input(self, level, f, args, kwargs):
        return "%s- %s(%s)" % \
            (level * indentchar, _name(f),
             ", ".join(map(repr, args) +
                       map(lambda i: "%s=%s" % (i[0], repr(i[1])),
                           kwargs.items())))

    def format_output(self, level, returnval):
        return "%s-> %s" % (level * indentchar, repr(returnval))


class Tracer(threading.local):
    def __init__(self, formatter=None):
        self.level = 0
        self.formatter = formatter or Formatter()

    def close(self):
        pass


class StdoutTracer(Tracer):
    def __init__(self):
        super(StdoutTracer, self).__init__()

    def trace(self, f, *args, **kwargs):
        print self.formatter.format_input(self.level, f, args, kwargs)
        self.level += 1
        try:
            r = f(*args, **kwargs)
        except Exception as e:
            r = e  # print the exception as the return val
            raise
        finally:
            self.level -= 1
            print self.formatter.format_output(self.level, r)
        return r


class PerThreadFileTracer(Tracer):
    def __init__(self, filename=None):
        super(PerThreadFileTracer, self).__init__()
        d = os.path.dirname(filename)
        if not os.path.exists(d):
            os.makedirs(d)
        self.outputfile = open(filename, 'w')

    def trace(self, f, *args, **kwargs):
        self.outputfile.write(self.formatter.format_input(self.level, f, args, kwargs) + "\n")
        self.level += 1
        try:
            r = f(*args, **kwargs)
        except Exception as e:
            r = e  # print the exception as the return val
            raise
        finally:
            self.level -= 1
            self.outputfile.write(self.formatter.format_output(self.level, r) + "\n")
        return r

    def close(self):
        self.outputfile.close()


def add_trace(f, tracer):
    def traced_fn(*args, **kwargs):
        return tracer.trace(f, *args, **kwargs)
    traced_fn.trace = True  # set flag so that we don't add trace more than once
    return traced_fn


def traceable(f):
    '''Returns true if f is the sort of object we want to trace, eg
       Callable and not a class.  Can override this behavior by
       replacing this function
    '''
    return callable(f)\
        and not isclass(f)\
        and not getattr(f, 'trace', None)  # already being traced


@contextmanager
def trace_on(objs, include_hidden=False, tracer=None, skip=None):
    tracer = tracer or StdoutTracer()
    origs = {}
    skip = skip or []
    for o in objs:
        replacements = {}
        for k in o.__dict__.keys():
            v = o.__dict__[k]
            if traceable(v) and getattr(v, '__name__', None) is not '__repr__' \
               and v not in skip \
               and (include_hidden or
                    not (include_hidden or k.startswith("_"))):
                replacements[k] = v
                # print "Replacing: " + k
                setattr(o, k, add_trace(v, tracer))
        origs[o] = replacements
    # print origs
    with closing(tracer):
        try:
            yield
        finally:  # set all the original values back
            for o in objs:
                originals = origs[o]
                for k in originals.keys():
                    setattr(o, k, originals[k])
