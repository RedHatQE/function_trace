
================
 Function_trace
================

Function_trace is a simple debugging library, inspired by similar libs
in Common Lisp and Clojure.  It captures function call arguments and
return values, and prints them in a nested fashion so you can easily
see which function is being called by which other function, what
arguments it was called with, and what its return value was.


Usage
=====

Trace blocks of code with the ``trace_on`` context manager.  It
accepts one positional argument, a list of modules and classes to be
traced.  When a class is traced, that includes all the methods defined
in that class, but not inherited methods.  When a module is traced,
that includes all the functions in that module, but does not include
any class methods defined in that module (you must specify the class
separately).

By default, the trace output is printed to stdout.  You can modify
this behavior by replacing ``function_trace.tracer`` with a function
that does whatever you like with the trace.  The tracer function
should have the signature ``(f, *args, **kwargs)`` which is the
function to trace, and the arguments to call the function with.  It
should call the function with the args at some point.  Note it is
preferable to catch any exceptions thrown by f, log them and re-raise
the exception.


Options
-------

* ``include_hidden`` if set to True, also trace functions whose name
  starts with ``_``.  Note, the ``__repr__`` function will never be
  traced.
* ``depths`` a dict where the keys are functions/methods and the
  values are integers representing the depth to which you want to
  trace that function/method.  For example a depth of 0 means "do not
  trace this function at all", even if it calls functions that are
  being traced.  A depth of 1 will trace this function but skip all
  tracing until it returns.  A depth of 2 will trace another level
  deeper.  Note, the depths represent the depth of the trace output,
  NOT the python call stack.
* ``tracer`` lets you specify a custom tracer object.  The simplest
  way to create it is to extend the ``Tracer`` class and override the
  ``trace_in`` and ``trace_out`` methods.  With a customm tracer you
  can do things like write the trace in any format, like HTML, JSON,
  XML etc, or send it over the network.


Examples
========

::

  from function_trace import trace_on

  with trace_on([Class1, module1, Class2, module2], include_hidden=True,
                depths={module1.check_thing: 1,
                        module2.unimportant_thing: 0
                        Class1.silly_thing: 0}):
      module1.function1("arg1", "arg2", option=True)
      x = new Class1()
      x.method1(arg1, arg2)


Output
------

::

  - module1.function1("arg1", "arg2", option=True)
  |    - module1.function2("arg2")
  |    |    - module1.check_thing()
  |    |    -> True
  |    -> "myresult"
  -> "myresult"
  - Class1.x(<Class1 object at 0xdeadbeef>, "arg1val", "arg2val")
  |    - module2.function1("arg2val")
  |    -> "foo"
  |    - Class2.y(<Class2 object at 0xabcd0001>, "arg1val")
  |    -> BadInputException("You can't call y with 'arg1val'!")
  -> BadInputException("You can't call y with 'arg1val'!")

* Methods will show the first argument ``self``.  By default,
  arguments and return values are printed using ``repr``, so if you
  want to see something more informative than ``<Class1 object at
  0xdeadbeef>``, you can define ``__repr__`` on ``Class1`` to print
  whatever you like (probably the values of various fields of that
  object).

* By default, exceptions that are raised by a function are printed as
  its return value.  This makes it possible to see an exception
  propagating down the stack. It is currently not possible to
  distinguish between a function call that returns an exception
  object, and one that raises that exception object (but functions
  that intentionally return Exceptions are rare anyway).
 
