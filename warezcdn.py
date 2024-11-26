# TODO: create unit tests
# TODO: implement a 'search and download' function
# TODO: create docstrings
# TODO: show steps of the process to get the download link
import argparse
import typing
import json
import re

from bs4 import BeautifulSoup
import requests

from utils import download_from_m3u8


host = 'warezcdn.link'
host_url = f'https://embed.{host}'


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
        serie_url = re.findall(r"var cachedSeasons = (?:\'|\")(.+)(?:\'|\")", script.string)
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
                audio_data = re.findall(r"let data = (?:\'|\")(.+)(?:\'|\")", script.string)
                if audio_data:
                    audio_data = audio_data[0]
                    break

            return json.loads(audio_data)


def get_parts_url(
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
        video_html_url = re.findall(r"window.location.href = (?:\'|\")(.+)(?:\'|\")", script.string)
        if video_html_url:
            video_html_url = video_html_url[0]
            break

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
            playlist_url = matches[0]
            break
        
    return playlist_url


# TODO: warn if prefered audio is unavaliable
def download_episode(ep_name: str, imdb: str, id: str, preferred_audio: typing.Literal['1', '2']):
    audios = get_audios(imdb, id, 'serie')
    for audio in audios:
        if audio['audio'] == preferred_audio:
            break

    if 'warezcdn' in audio['servers']:
        server = 'warezcdn'
    else:
        server = 'mixdrop'
    
    if server == 'warezcdn':
        parts_url = get_parts_url(imdb, audio['id'], server, audio['audio'], 'serie')
        
        download_from_m3u8(parts_url, f'{ep_name}.mp4')
    
    else:
        msg = "O episódio possui apenas o servido 'mixdrop', que ainda não é suportado."
        raise Exception(msg)


def download_serie(
        imdb: str, 
        season: int, 
        episodes: int | list[int] | typing.Literal['all'], 
        preferred_audio: typing.Literal['dublado', 'original']
    ):
    # get language id for prefered audio
    match preferred_audio:
        case 'dublado':
            lang = '2'
        
        case 'original':
            lang = '1'
    
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
        ep_name = f'{serie_info['title']} (S{season_number}E{ep_number}){ep_title}'
        id = episode_info['id']

        # download episode
        if episodes == 'all':
            download_episode(ep_name, imdb, id, lang)

        elif int(episode_info['name']) in episodes:
            print(ep_name)
            download_episode(ep_name, imdb, id, lang)
    

# TODO: warn if prefered audio is unavaliable
def download_filme(imdb: str, preferred_audio: typing.Literal['dublado', 'original']):
    filme_info = filme(imdb)

    audios = get_audios(imdb, filme_info['id'], 'filme')
    for audio in audios:
        if audio['audio'] == preferred_audio:
            break

    if 'warezcdn' in audio['servers']:
        server = 'warezcdn'
    else:
        server = 'mixdrop'
    
    if server == 'warezcdn':
        parts_url = get_parts_url(imdb, audio['id'], server, audio['audio'], 'serie')
        download_from_m3u8(parts_url, f'{filme_info['title']}.mp4')
    
    else:
        msg = "O episódio possui apenas o servidor 'mixdrop', que ainda não é suportado."
        raise Exception(msg)


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


    args = parser.parse_args()
    
    match args.action:
        case 'search':
            print(json.dumps(search(args.search), indent=2))
        
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
                    download_filme(args.imdb, args.audio)
                
                case 'serie':
                    if args.episodios[0] == -1:
                        args.episodios == 'all'

                    download_serie(args.imdb, args.temporada, args.episodios, args.audio)
                
                case _:
                    parser.print_help()
                    exit()
        
        case _:
            parser.print_help()