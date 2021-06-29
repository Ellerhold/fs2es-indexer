import os

from setuptools import setup


def read_project_file(path):
    proj_dir = os.path.dirname(__file__)
    path = os.path.join(proj_dir, path)
    with open(path, 'r') as f:
        return f.read()


setup(
    name='fs2es_indexer',
    version='0.2.1',
    description='Index files and directories into elastic search',
    long_description=read_project_file('README.md'),
    long_description_content_type='text/markdown',
    author='Matthias Kühne',
    author_email='matthias.kuehne@ellerhold.de',
    python_requires='>=3.0.0',
    packages=[
        'fs2es_indexer'
    ],
    install_requires=[
        'PyYaml',       # Debian 10 Buster: python3-yaml
        'elasticsearch'
    ],
    include_package_data=True,
    license='proprietary',
    scripts={
        'fs2es_indexer/fs2es-indexer'
    },
)
