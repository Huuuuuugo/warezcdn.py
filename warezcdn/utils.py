# TODO: create docstrings
import requests

import shutil
import time
import os
import re

from m3u8_downloader.downloader import Download
from m3u8_downloader.m3u8_downloader import M3U8Downloader


def download_m3u8(url: str, output_file: str):
    response = requests.get(url)
    with open(output_file, 'bw') as file:
        file.write(response.content)


def download_from_m3u8(url: str, output_file: str, temp_dir: str):
    # ask confirmatio if output file already exists
    if os.path.exists(output_file):
        choice = ''
        while choice not in ('sim', 's', 'nao', 'não', 'n'):
            choice = input(f'O arquivo \'{output_file}\' já existe! Quer substituí-lo (s/n)? ')
            if choice in ('nao', 'não', 'n'):
                return
    
    # get file name to show along the progress indicator 
    matches = re.findall(r"(?:/|\\)(?!.*(?:/|\\))(.+?\.mp4)", output_file)
    if matches:
        file_name = matches[0]
    else:
        file_name = output_file
    
    label = f'(warezcdn) {file_name}'

    # create output directory
    if os.path.dirname(output_file):
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # download playlist
    m3u8_path = f"{temp_dir}index.m3u8"
    download_m3u8(url, m3u8_path)

    # download parts
    M3U8Downloader(m3u8_path, output_file, label=label, temp_dir=temp_dir, max_downloads=10, ignore_exeptions=True).download()


def download_from_mixdrop(url: str, output_file: str, temp_dir: str):
    # ask confirmatio if output file already exists
    if os.path.exists(output_file):
        choice = ''
        while choice not in ('sim', 's', 'nao', 'não', 'n'):
            choice = input(f'O arquivo \'{output_file}\' já existe! Quer substituí-lo (s/n)? ')
            if choice in ('nao', 'não', 'n'):
                return

    # get file name to show along the progress indicator 
    temp_file = f'{temp_dir}/downloading.mp4'
    matches = re.findall(r"(?:/|\\)(?!.*(?:/|\\))(.+?\.mp4)", output_file)
    if matches:
        file_name = matches[0]
    else:
        file_name = output_file
    
    label = f'(mixdrop) {file_name}'

    try:
        download = Download(
            url, temp_file,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"},
            )
        download.start()
    
    # skip if range is unsatisfiable, which usually means it's 100% downloaded
    except requests.RequestException as e:
        if download.response.status_code == 416:
            index = download.download_list.index(download)
            download.download_list.pop(index)
            download = None
        else:
            raise e
    
    # wait for download to finnish and show progress
    print()
    if download is not None:
        while download.is_running:
            print(f'\033[F\r{label} {download.progress:.2f}%   ')
            time.sleep(0.1)
            
    print(f'\033[F\r{label} 100.00%   ')

    # move temp download to output file
    if os.path.dirname(output_file):
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
    shutil.move(temp_file, output_file)