import setuptools


setuptools.setup(
    version="0.0.1",
    license='mit',
    name='py-shell',
    author='nathan todd-stone',
    author_email='me@nathants.com',
    url='http://github.com/nathants/py-shell',
    packages=['shell'],
    install_requires=['argh==0.26.1',
                      'pyyaml==3.11'],
    description='for shelling out',
)