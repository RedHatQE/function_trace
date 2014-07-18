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
import functools
indentchar = "|   "


def _name(f):
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

def hashable(v):
    """Determine whether `v` can be hashed."""
    try:
        hash(v)
    except TypeError:
        return False
    return True

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
    '''Gets the func_code object for the given object if it's a function
       or method, otherwise the instance (that presumably has a
       __call__ method).

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
           depths = mapping of identifiers to depth'''
        self.functions = {}
        self.depths = {}
        for f in functions:
            ident, info_obj = _get_function_mapping(f)
            self.functions[ident] = info_obj
            if f in depths:
                self.depths[ident] = depths[f]

    def __init__(self, functions, formatter=None, depths=None):
        self.level = 0
        self.formatter = formatter or Formatter()
        self.lastframe = None
        self.framemaxdepths = []
        self._get_functions(functions, depths or {})
        #self.additional_depth = None

    def _get_id(self, frame):
        f = frame.f_code
        if f in self.functions:
            return f
        else:
            args, varargs, keywords, localz = inspect.getargvalues(frame)
 
            if args:
                # print "%s args %s" % (frame.f_code, args)
                # filename, lineno, function, code_context, index = inspect.getframeinfo(frame)

                try:
                    inst = localz[args[0]]
                except BaseException as e:
                    # print e
                    return None
                try:
                    if inst and hasattr(inst, '__call__')\
                       and hashable(inst):
                        return inst.__call__
                except:
                    pass
            return None

    
    def tracefunc(self, frame, event, arg):
        try:
            if event == 'call':
                ident = self._get_id(frame)
                if ident in self.functions:
                    additional_depth = self.depths.get(ident, None)
                    depths = [fmd[1] for fmd in self.framemaxdepths] or [sys.maxint]
                    # print depths
                    min_depth_limit = min(depths)

                    # print "min depth: %s" % min_depth_limit
                    if additional_depth is not None:
                        # if additional_depth == 0:
                        #     print "stop tracing on %s" % ident
                        #     return None
                        depth_limit = self.level + additional_depth
                        if depth_limit < min_depth_limit:
                            min_depth_limit = depth_limit
                            self.framemaxdepths.append((frame.f_back, depth_limit))
                            print "new depth limit %s from %s. %s" % (depth_limit, ident, self.framemaxdepths)
                            # print "pushing %s:%s" % (depth_limit, frame.f_back)

                    if self.level < min_depth_limit:
                        args = inspect.getargvalues(frame)
                        self.trace_in(_name(self.functions[ident]),
                                      [],
                                      args.locals)
                        self.level += 1
                    else:
                        return None

            elif event == 'return':
                ident = self._get_id(frame)
                if ident in self.functions:
                    if self.lastframe is frame:
                        self.lastframe = None
                    else:
                        self.level -= 1
                        self.trace_out(arg)
                        # print frame
                        # print self.framemaxdepths
                        if self.framemaxdepths and frame.f_back is self.framemaxdepths[-1][0]:
                            print "popping %s" % frame.f_back
                            self.framemaxdepths.pop()

            elif event == 'exception':
                ident = self._get_id(frame)
                if ident in self.functions:
                    self.lastframe = frame
                    self.level -= 1
                    self.trace_out(arg[0], exception=True)
                    # print frame.f_back
                    if self.framemaxdepths and frame.f_back is self.framemaxdepths[-1][0]:
                        print "popping %s" % frame.f_back
                        self.framemaxdepths.pop()

        except:
            raise
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
