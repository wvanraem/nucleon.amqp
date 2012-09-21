from setuptools import setup, find_packages


setup(
    name='nucleon.amqp',
    version='0.2.0',
    packages=find_packages(),
    namespace_packages=['nucleon'],
    install_requires=[
        'gevent==1.0b4',
    ],
    dependency_links=[
        'http://code.google.com/p/gevent/downloads/list',
    ]
)
