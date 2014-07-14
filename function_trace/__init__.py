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
from inspect import isclass, ismethod, getmembers
import threading
import os

indentchar = "|   "
thread_locals = threading.local()


def _name(f):
    mattr = getattr(f, '__module__', None)
    if mattr:
        nattr = getattr(f, "__name__", None)
    else:
        # partials
        fattr = getattr(f, 'func', None)
        if fattr:
            mattr = getattr(fattr, '__module__')
            nattr = getattr(fattr, '__name__') + '__partial__'
    return "%s.%s" % ((mattr or "module"), (nattr or "name"))


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


class Tracer(object):
    def __init__(self, formatter=None):
        self.level = 0
        self.max_depth = None
        self.formatter = formatter or Formatter()

    def trace(self, f, args, kwargs, additional_depth=None):
        # print "tracing " + str(f)
        prev_max = self.max_depth
        try:
            if additional_depth is not None:  # None means unlimited
                total_depth = self.level + additional_depth
                if self.max_depth is not None:
                    self.max_depth = min(self.max_depth, total_depth)
                else:
                    self.max_depth = total_depth
            if (self.max_depth is None or (self.level < self.max_depth)):
                self.trace_in(f, args, kwargs)
                self.level += 1

                try:
                    r = f(*args, **kwargs)
                except BaseException as e:
                    r = e  # print the exception as the return val
                    raise
                finally:
                    self.level -= 1
                    self.trace_out(r)
                return r
            else:
                return f(*args, **kwargs)
        finally:
            self.max_depth = prev_max

    def close(self):
        pass


class StdoutTracer(Tracer):
    def __init__(self):
        super(StdoutTracer, self).__init__()

    def trace_in(self, f, args, kwargs):
        print self.formatter.format_input(self.level, f, args, kwargs)

    def trace_out(self, r):
        print self.formatter.format_output(self.level, r)


class PerThreadFileTracer(Tracer):
    def __init__(self, filename=None):
        super(PerThreadFileTracer, self).__init__()
        d = os.path.dirname(filename)
        if not os.path.exists(d):
            os.makedirs(d)

        # keep file we're writing to outside the state of this instance
        # prevents replaced functions from trying to write to the wrong file
        thread_locals.outputfile = open(filename, 'w')

    def trace_in(self, f, args, kwargs):
        # print "in %s %s %s %s" % (str(thread_locals.outputfile), f, args, kwargs)
        thread_locals.outputfile.write(self.formatter.format_input(self.level, f, args, kwargs) + "\n")

    def trace_out(self, r):
        thread_locals.outputfile.write(self.formatter.format_output(self.level, r) + "\n")

    def close(self):
        # print "closing " + str(thread_locals.outputfile)
        thread_locals.outputfile.close()


def _copy_attrs(old, new):
    for a in ('__name__', '__doc__', '__module__'):
        if hasattr(old, a):
            setattr(new, a, getattr(old, a))


def add_trace(f, tracer, depth=None):
    def traced_fn(*args, **kwargs):
        return tracer.trace(f, args, kwargs, additional_depth=depth)
    traced_fn.trace = True  # set flag so that we don't add trace more than once
    #_copy_attrs(f, traced_fn)
    return traced_fn


def traceable(f):
    '''Returns true if f is the sort of object we want to trace, eg
       Callable and not a class.  Can override this behavior by
       replacing this function
    '''
    return (callable(f)
            and not isclass(f)
            and not getattr(f, 'trace', None))  # already being traced


def _defined_this_module(o, f):
    '''Returns true if f is defined in the module o (or true if o is a class)'''
    if isclass(o):
        return True
    else:
        return o.__name__ == getattr(f, '__module__', None)


def _get_func(m):
    '''Returns function given a function or method'''
    if ismethod(m):
        return m.im_func
    else:
        return m


@contextmanager
def trace_on(objs, include_hidden=False, tracer=None, depths=None):
    tracer = tracer or StdoutTracer()
    origs = {}
    depths = depths or {}

    # converts methods to functions, since that is what's in __dict__
    f_depths = {}
    for (k, v) in depths.items():
        f_depths[_get_func(k)] = v
    depths = f_depths

    for o in set(objs):
        replacements = {}
        for k in o.__dict__.keys():
            v = o.__dict__[k]
            if traceable(v) and getattr(v, '__name__', None) is not '__repr__' \
               and (v not in depths or depths[v] >= 0) \
               and _defined_this_module(o, v) \
               and (include_hidden or
                    not (include_hidden or k.startswith("_"))):
                replacements[k] = v
                # print "Replacing: %s %s %s , depth %s" % (k, o, v, depths.get(v, None))
                setattr(o, k, add_trace(v, tracer, depth=depths.get(v, None)))
        origs[o] = replacements
    # print origs
    with closing(tracer):
        try:
            yield
        finally:  # set all the original values back
            for o in objs:
                originals = origs[o]
                for k in originals.keys():
                    if getattr(originals[k], 'trace', None):
                        raise Exception("Original is lost: %s" % str(originals[k]))
                    # print "Restoring: %s %s %s" % (k, o, originals[k])

                    setattr(o, k, originals[k])


def all(module):
    '''Returns all classes in the given module plus the module itself.'''

    def traceable_class(c):
        return isclass(c) and not c.__name__.startswith('_') \
            and getattr(c, '__module__', None) == module.__name__  # make sure class was defined in that module

    matches = [i[1] for i in getmembers(module, traceable_class)]
    return [module] + matches
