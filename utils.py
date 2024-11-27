# TODO: add support for mixdrop downloads
# TODO: create docstrings
# TODO: create a local directory for unfinished downloads for mixdrop
import requests

import subprocess
import json
import time
import os
import re

from downloader import Download


class JSONManager():
    def __init__(self, json_path: str, default_value: dict|list):
        self.path = json_path

        # read content from the file if it already exists
        if os.path.exists(json_path):
            self.content = self.read()
        
        # create file with the default value if not
        else:
            self.content = self.save(default_value)
    
    def read(self):
        with open(self.path, 'r', encoding='utf8') as file:
            self.content = json.loads(file.read())
        
        return self.content
    
    def save(self, content: dict|list):
        with open(self.path, 'w', encoding='utf8') as file:
            self.content = content
            file.write(json.dumps(self.content, indent=2))


def download_m3u8(url: str, output_file: str):
    response = requests.get(url)
    with open(output_file, 'bw') as file:
        file.write(response.content)


def download_parts(m3u8_path: str, headers: dict = None, output_dir: str = './', max_downloads: int = 1):
    # fromat arguments
    if output_dir[-1] not in ('/', '\\'):
        output_dir += '/'
    
    if headers is None:
        headers = {}
    
    # create directory for parts
    parts_dir = f"{output_dir}parts/"
    os.makedirs(parts_dir, exist_ok=True)

    # create or read json that indicates all the downloaded parts
    parts_json_path = f"{output_dir}parts.json"
    parts_json = JSONManager(parts_json_path, [])

    # read list of finished downloads
    finished_downloads: list[str] = parts_json.read() # used to update parts.json
    skip_downloads = finished_downloads.copy() # used to check if has already been downloaded

    # download every url inside the playlist
    with open(m3u8_path, 'r', encoding='utf8') as file:
        # get line count to use as a progress indicator
        playlist = file.readlines()
        line_count = len(playlist)
        curr_line = 0
        print('0.00%')

        # iterate through every lline of the playlist
        active_downloads = []
        for line in playlist:
            curr_line += 1
            line = line.strip()

            # try to download if the line contains an url
            url = re.match(r"https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)", line)
            if url:
                url = url[0]
                part_name = f'{re.findall(r".*/(.+)\.", url)[0]}.mp4'
                file_name = f"{parts_dir}{part_name}"

                # skip if this part has already been downloaded
                if part_name in skip_downloads:
                    index = skip_downloads.index(part_name)
                    skip_downloads.pop(index)
                    continue
                
                # start download and append to list of downloads
                try:
                    d = Download(url, file_name, headers=headers, max_retries=5, try_continue=False)
                    d.start()
                    d.part_name = part_name # added to be inserted on the finished list later
                    active_downloads.append(d)

                except ValueError:
                    continue
                
                # wait if the limit of simultaneous downloads has been reached or all the file has been read
                while len(active_downloads) >= max_downloads or line_count == curr_line:
                    # check for download progress
                    for download in active_downloads:
                        if download.progress >= 100:
                            # update list of finished and active downloads
                            finished_downloads.append(download.part_name)
                            parts_json.save(finished_downloads)
                            active_downloads.pop(active_downloads.index(download))
                            break

                        time.sleep(0.01)
            
            print(f"\033[F\r{curr_line/(line_count/100):.2f}%")

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
    

def download_from_m3u8(url: str, output_file: str, temp_dir: str):
    m3u8_path = f"{temp_dir}/index.m3u8"
    download_m3u8(url, m3u8_path)

    parts_dir = download_parts(m3u8_path, output_dir=temp_dir, max_downloads=5)
    local_m3u8_path = create_local_m3u8(m3u8_path, parts_dir)
    concat(local_m3u8_path, output_file)


def download_from_mixdrop(url: str, output_file: str):
    try:
        download = Download(
            url, output_file,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"},
            )
        download.start()
    
    # skip if range is unsatisfiable, which usually means it's 100% downloaded
    except requests.RequestException as e:
        if download.response.status_code == 416:
            index = download.download_list.index(download)
            download.download_list.pop(index)
            matches = re.search(r"(?:/|\\)(.+?\.mp4)", output_file)
            if matches:
                print(f'{matches[0]} 100%')
            else:
                print(f'{output_file} 100%')
        else:
            raise e
    
    Download.wait_downloads()