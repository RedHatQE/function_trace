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
import inspect
import os
import sys
import itertools
import opcode

indentchar = "|   "


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
            (level * indentchar, f,
             ", ".join(map(repr, args) +
                       map(lambda i: "%s=%s" % (i[0], repr(i[1])),
                           kwargs.items())))

    def format_output(self, level, returnval, exception):
        return "%s-> %s%s" % (level * indentchar,
                              "!!!" if exception else "",
                              repr(returnval))


def _get_code(o):
    '''Gets the func_code object for the given object.'''
    if hasattr(o, 'func'):
        return o.func.func_code
    if hasattr(o, 'im_func'):
        return o.im_func.func_code
    if hasattr(o.__call__, 'im_func'):
        return o.__call__.im_func.func_code
    if hasattr(o, 'func_code'):
        return o.func_code
    return None


class Tracer(object):
    def __init__(self, functions, formatter=None, depths=None):
        self.functions = {_get_code(f): f for f in functions}
        self.code_objs = set(self.functions.keys())
        self.level = 0
        self.max_depth = None
        self.formatter = formatter or Formatter()
        self.depths = depths or {}
        self.lastframe = None
        #self.additional_depth = None

    def tracefunc(self, frame, event, arg):
        if event == 'call' and frame.f_code in self.code_objs:
            # print "code object %s " % frame.f_code
            f = self.functions[frame.f_code]
            additional_depth = self.depths.get(f, None)
            # print "addl: %s, max: %s " % (additional_depth, self.max_depth)
            if additional_depth is not None:  # None means unlimited
                total_depth = self.level + additional_depth
                if self.max_depth is not None:
                    self.max_depth = min(self.max_depth, total_depth)
                else:
                    self.max_depth = total_depth
                # print "max: %s" % self.max_depth
            if (self.max_depth is None or (self.level < self.max_depth)):
                args = inspect.getargvalues(frame)
                self.trace_in(_name(f),
                              [],
                              args.locals)
                self.level += 1
            else:
                return None

        elif event == 'return' and not frame.f_exc_type and frame.f_code in self.code_objs:
            if self.lastframe is frame:
                self.lastframe = None
            else:
                self.level -= 1
                self.trace_out(arg)
        elif event == 'exception' and frame.f_code in self.code_objs:
            self.lastframe = frame
            self.level -= 1
            self.trace_out(arg[0], exception=True)
        return self.tracefunc

    def close(self):
        pass


class StdoutTracer(Tracer):
    def __init__(self, functions, formatter=None, depths=None):
        super(StdoutTracer, self).__init__(functions, formatter=formatter, depths=depths)

    def trace_in(self, f, args, kwargs):
        print self.formatter.format_input(self.level, f, args, kwargs)

    def trace_out(self, r, exception=False):
        print self.formatter.format_output(self.level, r, exception)


class PerThreadFileTracer(Tracer):
    def __init__(self,  functions, formatter=None, depths=None, filename=None):
        super(PerThreadFileTracer, self).__init__(functions, formatter=formatter, depths=depths)
        d = os.path.dirname(filename)
        if not os.path.exists(d):
            os.makedirs(d)

        # keep file we're writing to outside the state of this instance
        # prevents replaced functions from trying to write to the wrong file
        self.outputfile = open(filename, 'w')

    def trace_in(self, f, args, kwargs):
        # print "in %s %s %s %s" % (str(self.outputfile), f, args, kwargs)
        self.outputfile.write(self.formatter.format_input(self.level, f, args, kwargs) + "\n")

    def trace_out(self, r, exception=False):
        self.outputfile.write(self.formatter.format_output(self.level, r, exception) + "\n")

    def close(self):
        print "closing " + str(self.outputfile)
        self.outputfile.close()


def _defined_this_module(parent, child):
    '''Returns true if f is defined in the module o (or true if o is a class)'''
    if inspect.ismodule(parent):
        return parent.__name__ == getattr(child, '__module__', None)
    return True


def mapcat(f, lst):
    return list(itertools.chain.from_iterable(map(f, lst)))


def all(o, include_hidden=False):
    '''Return all the functions/methods in the given object.'''
    def r(x, y):
        n, v = y
        if not n.startswith("__")\
           and (include_hidden or
                not (include_hidden or n.startswith("_")))\
           and _defined_this_module(o, v):
            if inspect.isclass(v):
                return list(x) + all(v)
            else:
                return list(x) + [v]
        else:
            return list(x)
    return reduce(r, inspect.getmembers(o, callable), [])


@contextmanager
def trace_on(objs=None, tracer=None):
    tracer = tracer or StdoutTracer(objs)
    sys.settrace(tracer.tracefunc)
    with closing(tracer):
        try:
            yield
        finally:
            sys.settrace(None)
