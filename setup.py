from setuptools import setup, find_packages

setup(
    name='warezcdn',
    version='1.0.0',
    packages=find_packages(include=['warezcdn', 'm3u8_downloader']),
    entry_points={
        'console_scripts': [
            'warezcdn = warezcdn.warezcdn:main',
        ],
    },
)
