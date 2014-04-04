from setuptools import setup, find_packages
setup(
    name="function_trace",
    version="0.2",
    packages=find_packages(),

    # metadata for upload to PyPI
    author="Jeff Weiss",
    author_email="jweiss@redhat.com",
    description="Hierarchical trace of function/method call arguments and return values",
    license="PSF",
    keywords="trace debugging",
    url="https://github.com/RedHatQE/function_trace",

    # could also include long_description, download_url, classifiers, etc.
)
