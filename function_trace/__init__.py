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

indentchar = "|   "


def _name(f):
    '''Get an appropriate name for the object, for printing to the trace log'''

    nattr = None
    mattr = getattr(f, '__module__', None)
    if mattr:
        nattr = getattr(f, "__name__", None)
    else:
        # partials
        fattr = getattr(f, 'func', None)
        if fattr:
            mattr = getattr(fattr, '__module__')
            nattr = getattr(fattr, '__name__') + '__partial__'
    if mattr and nattr:
        return "%s.%s" % (mattr, nattr)
    else:
        return repr(f)


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


def _get_function_mapping(o):
    '''Returns a 2-tuple, with the first element being the object
       belonging to the function/method that can be recognized from
       the Frame info, the second element is an object that contains
       info that can be printed to the trace log.

    '''
    # for regular functions, the identifier is the code object that appears in the frame
    # and the function itself is where the tracing info lies
    if inspect.ismethod(o) or inspect.isfunction(o):
        if hasattr(o, 'func'):
            i = o.func.func_code
        elif hasattr(o, 'im_func'):
            i = o.im_func.func_code
        elif hasattr(o.__call__, 'im_func'):
            i = o.__call__.im_func.func_code
        elif hasattr(o, 'func_code'):
            i = o.func_code
        return (i, o)

    # for objects that implement __call__, like MultiMethods, the identifier is the instance
    # since each one is conceptually a different function.  The tracing info is really just
    # the module and the function's name is '__call__'.  The first arg is what's important
    # (the instance)
    if hasattr(o, '__call__'):
        #print "got mm %s" % o
        return (o.__call__, o.__call__)
    return None


class Tracer(object):
    def _get_functions(self, functions, depths):
        '''sets some attributes:
           functions = mapping of identifiers to functions
           depths = mapping of identifiers to depth
        '''
        self.functions = {}
        self.depths = {}
        for f in functions:
            ident, info_obj = _get_function_mapping(f)
            self.functions[ident] = info_obj
            if f in depths:
                self.depths[ident] = depths[f]

    def __init__(self, functions, formatter=None, depths=None):
        self.formatter = formatter or Formatter()
        self.exception_frame = None
        # keep our own call stack of just frames being traced
        self.tracedframes = []  # tuples of (frame, maxdepth, is_traced)
        self._get_functions(functions, depths or {})

    def _get_id(self, frame):
        '''
        Given a frame, figure out what function/method is being called.
        '''
        f = frame.f_code
        if f in self.functions:
            return f  # if it's in the functions dict, we know it's correct
        else:
            # it could be an object that implements __call__.  Find __call__.
            args, varargs, keywords, localz = inspect.getargvalues(frame)
            if args:
                try:
                    # first arg is self, the instance
                    cf = localz[args[0]].__call__
                    if cf.im_func.func_code is f and cf in self.functions:
                        return cf
                except BaseException:
                    pass
            return None

    def _min_depths(self):
        '''Depth-controlled functions will limit the displayed call depth,
           find the most restrictive one (the minimum depth)'''
        depths = [fmd[1] for fmd in self.tracedframes] or [sys.maxint]
        return min(depths)

    @property
    def level(self):
        return len(self.tracedframes)

    def tracefunc(self, frame, event, arg):
        try:
            if event == 'call':
                ident = self._get_id(frame)
                if ident:
                    additional_depth = self.depths.get(ident, None)
                    min_depth_limit = self._min_depths()
                    if self.level < min_depth_limit:
                        if additional_depth is not None:
                            next_depth_limit = self.level + additional_depth
                            if next_depth_limit < min_depth_limit:
                                min_depth_limit = next_depth_limit

                    if self.level < min_depth_limit:
                        args = inspect.getargvalues(frame)
                        self.trace_in(_name(self.functions[ident]),
                                      [],
                                      args.locals)
                    if self.level <= min_depth_limit:
                        self.tracedframes.append((frame.f_back, min_depth_limit, self.level < min_depth_limit))

            elif event == 'return':
                # print frame.f_code
                if self.exception_frame:
                    self.exception_frame = None
                elif self.tracedframes and self.tracedframes[-1][0] is frame.f_back:
                    # print self.tracedframes
                    if self.tracedframes[-1][2]:
                        # self.trace_out("%s: %s" % (self._get_id(frame), arg))
                        self.trace_out(arg)
                    self.tracedframes.pop()

            elif event == 'exception':
                if self.tracedframes and self.tracedframes[-1][0] is frame.f_back:
                    # since both return and exception events get called for exceptions,
                    # save this frame so that we know it's the same trace entry when we get the
                    # return event.

                    self.exception_frame = frame
                    if self.tracedframes[-1][2]:
                        # self.trace_out("%s: %s" % (self._get_id(frame), arg))
                        self.trace_out(arg[0], exception=True)
                    self.tracedframes.pop()
        except:
            pass # just swallow errors to avoid interference with traced processes
        return self.tracefunc

    def close(self):
        pass


class StdoutTracer(Tracer):
    '''Print trace to stdout'''
    def __init__(self, functions, formatter=None, depths=None):
        super(StdoutTracer, self).__init__(functions, formatter=formatter, depths=depths)

    def trace_in(self, f, args, kwargs):
        print self.formatter.format_input(self.level, f, args, kwargs)

    def trace_out(self, r, exception=False):
        print self.formatter.format_output(self.level-1, r, exception)


class PerThreadFileTracer(Tracer):
    '''Print trace to a file. To get thread safety, use a different
       instance of this tracer for each thread.'''
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
        self.outputfile.write(self.formatter.format_output(self.level-1, r, exception) + "\n")

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
        '''Return list of functions x plus all the function members of y'''
        n, v = y  # getmembers returns name/value tuples
        if not n.startswith("__")\
           and (include_hidden or
                not (include_hidden or n.startswith("_")))\
           and _defined_this_module(o, v):
            if inspect.isclass(v):
                # print "adding class %s" % v
                x.extend(all(v))
                return x
            else:
                # print "adding function %s " % v
                x.append(v)
                return x
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
