import logging
import re
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, PEP_DOC_URL
from outputs import control_output
from utils import find_tag, get_response


def whats_new(session):
    """
    Вывод списка изменений в python в формате:
    'Ссылка на статью', 'Заголовок', 'Редактор, Автор'
    """
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    response = get_response(session, whats_new_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div',
                           attrs={'class': 'toctree-wrapper compound'})
    sections_by_python = div_with_ul.find_all(
                            'li', attrs={'class': 'toctree-l1'})
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = section.find('a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )
    return results


def latest_versions(session):
    """
    Вывод списка версий python в формате:
    'Ссылка на документацию', 'Версия', 'Статус'
    """
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    sidebar = find_tag(soup, 'div', class_='sphinxsidebarwrapper')
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
        else:
            raise Exception('Ничего не нашлось')
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        Link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (Link, version, status)
        )
    return results


def download(session):
    """
    Скачивание zip-архива с документацией в формате pdf.
    """
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    table_tag = find_tag(soup, 'table')
    pdf_a4_tag = find_tag(table_tag, 'a',
                          {'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def pep(session):
    """
    Вывод списка статусов pep в формате:
    'Статус', 'Количество'.
    Проверка на соответствие статусов в таблице
    и на странице PEP.
    """
    response = get_response(session, PEP_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')
    section_tags = find_tag(soup, 'section', attrs={'id': 'numerical-index'})
    body_tag = find_tag(section_tags, 'tbody')
    tr_tags = body_tag.find_all('tr')
    total_pep_sum = 0
    pep_types_sum = {}
    result = [('Статус', 'Количество')]
    for tr_tag in tqdm(tr_tags):
        total_pep_sum += 1
        table_pep = find_tag(tr_tag, 'td')
        table_pep = table_pep.text[1:]
        a_tag = find_tag(tr_tag, 'a',
                         attrs={'class': 'pep reference internal'})
        pep_url = urljoin(PEP_DOC_URL, a_tag['href'])
        response = get_response(session, pep_url)
        if response is None:
            return
        soup = BeautifulSoup(response.text, features='lxml')
        status = soup.find(string='Status')
        statuse_parent = status.find_parent()
        current_status = statuse_parent.find_next_sibling().text
        try:
            if current_status not in EXPECTED_STATUS[table_pep]:
                logging.info(
                        f'Несовпадающие статусы: '
                        f'{pep_url} '
                        f'Cтатус в карточке: {current_status} '
                        f'Ожидаемые статусы: {EXPECTED_STATUS[table_pep]} '
                    )
        except KeyError:
            logging.error('Такого статуса не существует')
        pep_types_sum[current_status] = pep_types_sum.get(
                                            current_status, 0) + 1
    pep_types_sum['Total'] = total_pep_sum
    result.extend(pep_types_sum.items())
    return result


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')

    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')

    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()

    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)

    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
