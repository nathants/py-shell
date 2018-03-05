import setuptools

setuptools.setup(
    version="0.0.1",
    license='mit',
    name='py-shell',
    author='nathan todd-stone',
    author_email='me@nathants.com',
    url='http://github.com/nathants/py-shell',
    packages=['shell'],
    python_requires='>=3.6',
    install_requires=['argh >0.26, <0.27',
                      'pyyaml >3, <4',
                      'py-util'],
    dependency_links=['https://github.com/nathants/py-util/tarball/4d1fe20ecfc0b6982933a8c9b622b1b86da2be5e#egg=py-util-0.0.1'],
    description='for shelling out',
)
