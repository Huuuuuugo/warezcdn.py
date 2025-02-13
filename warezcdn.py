# TODO: create unit tests
# TODO: implement a 'search and download' function
# TODO: create docstrings
# TODO: show steps of the process to get the download link
import argparse
import typing
import shutil
import json
import re
import os

from bs4 import BeautifulSoup
import STPyV8
import requests

from utils import download_from_m3u8, download_from_mixdrop


host = 'warezcdn.link'
host_url = f'https://embed.{host}'
temp_download_dir = './.download/'


def search(search_term: str):
    response = requests.post(
        f'{host_url}/includes/ajax.php', 
        headers={'Host': host}, 
        data={'searchBar': search_term},
        allow_redirects=False
        )
    
    return response.json()


def serie(imdb: str):
    #  get referer url
    referer_url = f'{host_url}/serie/{imdb}'
    referer_response = requests.get(referer_url)

    # extract url for getting the series info from the acquired html
    html = BeautifulSoup(referer_response.content, 'html.parser')
    scripts = html.find_all('script')
    for script in scripts:
        serie_url = re.findall(r"var cachedSeasons = (?:\'|\")(.+)(?:\'|\")", script.text)
        if serie_url:
            serie_url = f'{host_url}/{serie_url[0]}'
            break
    
    # request series info and return json response
    serie = search(imdb)['list']['0']
    seasons = requests.get(serie_url, headers={'Referer': referer_url})

    serie_info = serie | seasons.json()

    return serie_info


def filme(imdb: str):
    return search(imdb)['list']['0']


def get_audios(imdb: str, id: str, type: typing.Literal['movie', 'filme', 'serie']):
    if type == 'movie':
        type = 'filme'

    referer_url = f'{host_url}/{type}/{imdb}'

    match type:
        case 'serie':
            # request audio data
            request_url = f'{host_url}/core/ajax.php?audios={id}'

            response = requests.get(
                request_url,
                headers={'Referer': referer_url}
                )
    
            return json.loads(response.json())
        
        case 'filme':
            # get referer html
            response = requests.get(referer_url)

            # extract audio data from the referer html
            html = BeautifulSoup(response.content, 'html.parser')
            scripts = html.find_all('script')
            for script in scripts:
                audio_data = re.findall(r"let data = (?:\'|\")(.+)(?:\'|\")", script.text)
                if audio_data:
                    audio_data = audio_data[0]
                    break

            return json.loads(audio_data)


def get_video_url(
        imdb: str,
        id: str, 
        server: typing.Literal['warezcdn', 'mixdrop'], 
        lang: typing.Literal['1', '2'], 
        type: typing.Literal['movie', 'filme', 'serie']
    ):
    if type == 'movie':
        type = 'filme'

    referer_url = f'{host_url}/{type}/{imdb}'
    embed_referer_url = f'{host_url}/getEmbed.php?id={id}&sv={server}&lang={lang}'
    play_url = f'{host_url}/getPlay.php?id={id}&sv={server}'

    # get referer and embed to avoid bot detection
    requests.get(referer_url)
    requests.get(
        embed_referer_url,
        headers={'Referer': referer_url}
        )
    
    # get embed play html
    play_response = requests.get(
        play_url,
        headers={'Referer': embed_referer_url}
        )
    
    # extract url to the video player from play_html
    play_html = BeautifulSoup(play_response.content, 'html.parser')
    scripts = play_html.find_all('script')
    for script in scripts:
        video_html_url = re.findall(r"window.location.href = (?:\'|\")(.+)(?:\'|\")", script.text)
        if video_html_url:
            video_html_url = video_html_url[0]
            break

    match server:
        case 'warezcdn':
            # extract information about the video from video_html_url
            video_host = re.findall(r"https://(.+?)/", video_html_url)[0]
            video_host_url = f'https://{video_host}'
            video_hash = re.findall(r"/([\w]+?)(?:$|\?)", video_html_url)[0]

            # make request for master.m3u8 url based on data from video_html_url
            master_request_url = f'{video_host_url}/player/index.php?data={video_hash}&do=getVideo'

            master_m3u8_url = requests.post(
                master_request_url,
                data={'hash': video_hash, 'r': ''},
                headers={'X-Requested-With': 'XMLHttpRequest'}
                )
            master_m3u8_url = master_m3u8_url.json()['videoSource']

            # extract the url for the playlist containing all the parts from master.m3u8
            master_m3u8 = requests.get(master_m3u8_url).text
            for line in master_m3u8.split('\n'):
                matches = re.match(r"https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})(:\d+)?(/[^\s]*)?", line)
                if matches:
                    video_url = matches[0]
                    break
        
        case 'mixdrop':
            # requests html for the video player on mixdrop
            video_html_response = requests.get(
                video_html_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0"}
                )
            
            # extract the obfuscated json that leads to the download url
            video_html = BeautifulSoup(video_html_response.content, 'html.parser')
            scripts = video_html.find_all('script')
            for script in scripts:
                if 'MDCore' in str(script.text):
                    matches = re.findall(r"eval\((.+)\)", script.text)
                    if matches:
                        obfuscated_json = matches[0]
                        break

            # give a name to the deobfuscation function
            obfuscated_json = re.sub(r"function\(p,a,c,k,e,d\)", 'function deobfuscate(p,a,c,k,e,d)', obfuscated_json)
            # add a function call to the parameter given
            obfuscated_json = re.sub(r"return p}\(", 'return p}\ndeobfuscate(', obfuscated_json)

            # run obfuscated json to get the video download url
            with STPyV8.JSContext() as ctxt:
                mdcore = ctxt.eval(obfuscated_json)

            video_url = f'https:{re.findall(r"MDCore.wurl=\"(.+?)\"", mdcore)[0]}'
    
    return video_url


def download_episode(
        ep_name: str, 
        imdb: str, 
        id: str, 
        preferred_audio: typing.Literal['1', '2'], 
        prefered_server: typing.Literal['warezcdn', 'mixdrop']
        ):
    # get audio optiona valiable for the file
    audios = get_audios(imdb, id, 'serie')
    
    ep_name = re.sub(r"[\:\*\?\"\<\>\|]", '', ep_name)

    # selects the prefered audio, if avaliable
    # if not avaliable, selects whatever is avaliable instead
    for audio in audios:
        if audio['audio'] == preferred_audio:
            break
    if audio['audio'] != preferred_audio:
        print("Áudio selecionado indisponível!")
    
    # selects the prefered server, if avaliable
    # if not avaliable, selects whatever is avaliable instead
    if prefered_server in audio['servers']:
        server = prefered_server
    else:
        print("Servidor selecionado indisponível!")
        server = audio['servers']
    
    # get download url and download from the correct server
    video_url = get_video_url(imdb, audio['id'], server, audio['audio'], 'serie')

    # create temporary directory for the download
    temp_dir = f'{temp_download_dir}{id}{audio['id']}/'
    os.makedirs(temp_dir, exist_ok=True)

    match server:
        case 'warezcdn':
            download_from_m3u8(video_url, f'{ep_name}.mp4', temp_dir)
        
        case 'mixdrop':
            download_from_mixdrop(video_url, f'{ep_name}.mp4', temp_dir)

    # remove temp dir after finished
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


def download_serie(
        imdb: str, 
        season: int, 
        episodes: int | list[int] | typing.Literal['all'], 
        preferred_audio: typing.Literal['dublado', 'original'],
        prefered_server: typing.Literal['warezcdn', 'mixdrop'],
        folders_mode: bool = False
    ):
    # get language id for prefered audio
    match preferred_audio:
        case 'dublado':
            lang = '2'
        
        case 'original':
            lang = '1'
    
    server = prefered_server
    
    # turn single episode into list
    if isinstance(episodes, int):
        episodes = [episodes]

    # get info about the serie
    serie_info = serie(imdb)

    # get selected season
    for season_info in serie_info['seasons'].values():
        if season_info['name'] == str(season):
            break
    
    # download selected episode
    for episode_info in season_info['episodes'].values():
        # get info for ep_name
        season_number = season_info['name'].zfill(2)
        ep_number = episode_info['name'].zfill(2)
        ep_title = episode_info['titlePt']

        # use episode title only if it's neither None nor a placeholder
        if ep_title is not None:
            if re.match(r"Episódio \d+", ep_title):
                ep_title = None
        if ep_title:
            ep_title = f' - {ep_title}'
        else:
            ep_title = ''
        
        # create episode name string a get episode id
        if folders_mode:
            ep_name = f'{serie_info['title']}/{season_number}/{ep_number}{ep_title}'
        else:
            ep_name = f'{serie_info['title']} (S{season_number}E{ep_number}){ep_title}'

        id = episode_info['id']

        # download episode
        if episodes == 'all':
            download_episode(ep_name, imdb, id, lang, server)

        elif int(episode_info['name']) in episodes:
            download_episode(ep_name, imdb, id, lang, server)
    

def download_filme(
        imdb: str, 
        preferred_audio: 
        typing.Literal['dublado', 'original'],
        prefered_server: typing.Literal['warezcdn', 'mixdrop']
        ):
    filme_info = filme(imdb)
    filme_name = re.sub(r"[\:\*\?\"\<\>\|]", '', filme_info['title'])


    # get audio options avaliable for the file
    audios = get_audios(imdb, filme_info['id'], 'filme')

    # selects the prefered audio, if avaliable
    # if not avaliable, selects whatever is avaliable instead
    for audio in audios:
        if audio['audio'] == preferred_audio:
            break
    if audio['audio'] != preferred_audio:
        print("Áudio selecionado indisponível!")
    
    # selects the prefered server, if avaliable
    # if not avaliable, selects whatever is avaliable instead
    if prefered_server in audio['servers']:
        server = prefered_server
    else:
        print("Servidor selecionado indisponível!")
        server = audio['servers']

    # create temporary directory for the download
    temp_dir = f'{temp_download_dir}{filme_info['id']}{audio['id']}'
    os.makedirs(temp_dir, exist_ok=True)
    
    # get download url and start downloading from the correct server
    video_url = get_video_url(imdb, audio['id'], server, audio['audio'], 'filme')
    match server:
        case 'warezcdn':
            download_from_m3u8(video_url, f'{filme_name}.mp4', temp_dir)
        
        case 'mixdrop':
            download_from_mixdrop(video_url, f'{filme_name}.mp4', temp_dir)
    
    # remove temp dir after finished
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparser = parser.add_subparsers(dest='action', help='comandos disponíveis:')

    # search parser
    search_parser = subparser.add_parser('search', help='faz uma busca na API.')
    search_parser.add_argument('search', nargs=1, type=str, help='o termo que será buscado.')


    # info parser 
    info_parser = subparser.add_parser('info', help='coleta informações sobre determinado filme ou série.')
    info_subparser = info_parser.add_subparsers(dest='variant')

    # filme parser
    info_filme_parser = info_subparser.add_parser('filme', help='coleta informações de um filme.')
    info_filme_parser.add_argument(
        '-imdb', '--imdb', 
        type=str, required=True, 
        help='id do filme no imdb.'
    )

    # serie parser
    info_serie_parser = info_subparser.add_parser('serie', help='cole informações de uma série.')
    info_serie_parser.add_argument(
        '-imdb', '--imdb', 
        type=str, required=True, 
        help='id da série filme no imdb.'
    )


    # download parser
    download_parser = subparser.add_parser('download', help='coleta informações sobre determinado filme ou série.')
    download_subparser = download_parser.add_subparsers(dest='variant')

    # filme parser
    download_filme_parser = download_subparser.add_parser('filme', help='coleta informações de um filme.')
    download_filme_parser.add_argument(
        '-imdb', '--imdb', 
        type=str, required=True, 
        help='id do filme no imdb.'
    )
    download_filme_parser.add_argument(
        '-a', '--audio', 
        choices=['dublado', 'original'], required=True, 
        help='preferência de áudio (dublado ou original).'
    )
    download_filme_parser.add_argument(
        '-s', '--servidor', 
        choices=['warezcdn', 'mixdrop'], required=True, 
        help='preferência de servidor (warezcdn ou mixdrop).'
    )

    # serie parser
    download_serie_parser = download_subparser.add_parser('serie', help='cole informações de uma série.')
    download_serie_parser.add_argument(
        '-imdb', '--imdb', 
        type=str, required=True, 
        help='id da série filme no imdb.'
    )
    download_serie_parser.add_argument(
        '-t', '--temporada', 
        type=int, required=True,
        help='número da temporada.'
    )
    download_serie_parser.add_argument(
        '-e', '--episodios', 
        type=int, required=True, nargs='+',
        help='número dos episódios que serão baixados (-1 = todos).'
    )
    download_serie_parser.add_argument(
        '-a', '--audio', 
        choices=['dublado', 'original'], required=True, 
        help='preferência de áudio (dublado ou original).'
    )
    download_serie_parser.add_argument(
        '-s', '--servidor', 
        choices=['warezcdn', 'mixdrop'], required=True, 
        help='preferência de servidor (warezcdn ou mixdrop).'
    )
    download_serie_parser.add_argument(
        '--criar-pastas', 
        action='store_true', 
        help='criar caminho de pastas \'série/temporada/episódio.mp4\'.'
    )


    args = parser.parse_args()
    
    match args.action:
        case 'search':
            results = search(args.search)
            print(f'Resultados: {results['count']}')
            input()

            for key in results['list'].keys():
                item = results['list'][key]
                print(f'[{int(key)+1}/{results['count']}]')
                print(f'Nome: {item['title']}')
                print(f'IMDb: {item['imdb']}')
                print(f'Tipo: {item['type']}')
                print(f'Ano: {item['year']}')
                input()
        
        case 'info':
            match args.variant:
                case 'filme':
                    print(json.dumps(filme(args.imdb), indent=2))
                
                case 'serie':
                    print(json.dumps(serie(args.imdb), indent=2))
                
                case _:
                    parser.print_help()
                    exit()
                
        case 'download':
            match args.variant:
                case 'filme':
                    download_filme(args.imdb, args.audio, args.servidor)
                
                case 'serie':
                    if args.episodios[0] == -1:
                        args.episodios = 'all'

                    download_serie(args.imdb, args.temporada, args.episodios, args.audio, args.servidor, args.criar_pastas)
                
                case _:
                    parser.print_help()
                    exit()
        
        case _:
            parser.print_help()