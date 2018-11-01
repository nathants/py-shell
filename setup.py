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
    dependency_links=['https://github.com/nathants/py-util/tarball/fa60dbf761a61beb94614af89240fd5986d26786#egg=py-util-0.0.1'],
    description='for shelling out',
)
