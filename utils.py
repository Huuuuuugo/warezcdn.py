# TODO: add support for mixdrop downloads
# TODO: create docstrings
# TODO: create a local directory for unfinished downloads from warez or mixdrop
import requests

from tempfile import TemporaryDirectory
import subprocess
import time
import os
import re

from downloader import Download


def download_m3u8(url: str, output_file: str):
    response = requests.get(url)
    with open(output_file, 'bw') as file:
        file.write(response.content)


# TODO: continue download if failed
#   change 'download_from_m3u8' path from a temp dir to combination of file id and audio id
#   skip parts already present on the parts directory
#   delete path after finished
def download_parts(m3u8_path: str, headers: dict = None, output_dir: str = './', max_downloads: int = 1):
    # fromat arguments
    if output_dir[-1] not in ('/', '\\'):
        output_dir += '/'
    
    if headers is None:
        headers = {}
    
    # create directory for parts
    parts_dir = f"{output_dir}parts/"
    os.makedirs(parts_dir)

    # download every url inside the playlist
    with open(m3u8_path, 'r', encoding='utf8') as file:
        playlist = file.readlines()
        line_count = len(playlist)
        curr_line = 0
        print('0.00%')

        for line in playlist:
            curr_line += 1
            line = line.strip()
            url = re.match(r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)", line)
            if url:
                url = url[0]
                file_name = f"{parts_dir}{re.findall(r".*/(.+)\.", url)[0]}.mp4"

                try:
                    Download(url, file_name, headers=headers, max_retries=5, try_continue=False).start()

                except ValueError:
                    continue
                
                while Download.get_running_count() >= max_downloads:
                    time.sleep(0.01)
            
            print(f"\033[F\r{curr_line/(line_count/100):.2f}%")
        
    Download.wait_downloads(False, 5)

    return parts_dir


# TODO: make it ignore invalid links, such as links with unsatisfiable ranges
def create_local_m3u8(m3u8_path: str, parts_dir: str):
    # fromat arguments
    if parts_dir[-1] not in ('/', '\\'):
        parts_dir += '/'
    
    full_parts_dir = os.path.abspath(parts_dir) + '/'

    # create filter function to properly order the files inside the given directory
    def extract_number(file_name):
        number = re.sub(r'\D', '', file_name)
        return int(number) if number else 0

    # get files list and order them
    parts = [file for file in os.listdir(parts_dir) if file.rsplit('.', 1)[-1] == 'mp4']
    parts = sorted(parts, key=extract_number)

    # create local m3u8 file
    local_m3u8_path = f'{parts_dir}local.m3u8'
    with open(m3u8_path, 'r') as playlist:
        with open(local_m3u8_path, 'w') as output:
            for line in playlist:
                line = line.strip()
                if re.match(r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)", line):
                    output.write(f"{full_parts_dir}{parts.pop(0)}\n")
                
                else:
                    output.write(f"{line}\n")

    return local_m3u8_path


# TODO: implement ability to pass custom arguments to ffmpeg
def concat(local_m3u8_path: str, output_file: str):
    # run ffmpeg to concatenate files
    print(os.getcwd())
    subprocess.run(["ffmpeg",
                    "-i", local_m3u8_path, 
                    "-c", "copy",
                    f"{output_file}"
                    ])
    

# TODO: change to default temp folder
# TODO: retry if download fails
def download_from_m3u8(url: str, output_file: str):
    with TemporaryDirectory(dir='') as path:
        m3u8_path = f"{path}/index.m3u8"
        download_m3u8(url, m3u8_path)

        parts_dir = download_parts(m3u8_path, output_dir=path, max_downloads=5)
        local_m3u8_path = create_local_m3u8(m3u8_path, parts_dir)
        concat(local_m3u8_path, output_file)


def download_from_mixdrop(url: str, output_file: str):
    Download(
        url, output_file, max_retries=6,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"},
        ).start()
    
    Download.wait_downloads()
    print()