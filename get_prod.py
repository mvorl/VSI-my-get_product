#!/usr/bin/env python
from pathlib import Path
import requests
import re
import json
# import shutil
import wget
import ssl
import warnings

from bs4 import BeautifulSoup

# Data to retrieve the open source product list
PROD_LIST_LINK = 'https://products.vmssoftware.com'
PROD_LIST_ID = 'hs_cos_wrapper_main_content-module-2'
PROD_LIST_REGEXP = re.compile(r'^\s*resources:\s*(.+),$', flags=re.MULTILINE)

# Data to retrieve the individual open source product
PROD_BASE_LINK = 'https://products.vmssoftware.com'
PROD_DOWNLOAD_CSS = '.single-solution__downloads-list'
PROD_REGEXP = re.compile(r'(https?://vmssoftware.com/openkits/(?:alp|i64|x86)opensource/([^.]+\.zip(?:exe)?))',
                         flags=re.IGNORECASE)

# Use cache? And where should it be?
USE_CACHE = True
CACHE_DIR = Path(__file__).parent / 'cache'

# Turn off SSL verification because of our dumb company firewall
SSL_VERIFY = False

# Just some syntactic sugar
DisplayList = list[str]
IndexList = list[int]
ProductInfo = dict[str, str | int | None | dict]

# Help text for list menu selection (taken from PRODUCT INSTALL)
HELP_TEXT = """
    Type the number representing each selected menu item.  Separate your
    answers with commas.  You may also select a range of numbers by using
    a hyphen between the starting and ending numbers.  The range can be
    specified in any order, smallest to highest, or highest to smallest.
    For example: 1-3, 5, 7, 11-9
"""


class Products:
    session = requests.Session()
    PLATFORM = {'alpha': 'AXP', 'integrity': 'I64', 'x86': 'x86'}

    def __init__(self):
        self.data_list = None
        self.link = PROD_LIST_LINK
        self.cache_file = CACHE_DIR / 'products.html'

    def _get_page_text(self) -> str:
        if USE_CACHE and self.cache_file.exists():
            print(f'Using cached {self.__class__.__name__} data from {self.cache_file.name}')
            with self.cache_file.open('rt') as f:
                page_text = f.read()
        else:
            print(f'Retrieving {self.__class__.__name__} data from {self.link}')
            response = self.session.get(url=self.link, verify=SSL_VERIFY)
            response.raise_for_status()
            page_text = response.text
            if USE_CACHE:
                with self.cache_file.open('wt') as f:
                    f.write(page_text)
        return page_text

    def _get_data(self) -> bool:
        soup = BeautifulSoup(self._get_page_text(), 'html.parser')
        container = soup.find(id=PROD_LIST_ID)
        script_text = container.find('script').text
        m = re.search(PROD_LIST_REGEXP, script_text)
        if not m:
            return False
            # raise ValueError('No product data found on webpage')
        self.data_list = json.loads(m.group(1))
        return True

    def get_data_list(self) -> DisplayList:
        if self.data_list is None:
            if not self._get_data():
                return []
        lst = []
        idx = 0
        for prod in sorted(self.data_list, key=lambda p: p['title'].lower()):
            if prod['open_source'][0]['name'] != 'Yes':
                prod['_index'] = -1
                continue
            prod['_index'] = idx
            idx += 1
            entry = prod['title']
            for platform in ('alpha', 'integrity', 'x86'):
                version = prod[platform]
                if version and version != 'not ported':  # special case for GNUplot x86
                    rel_date_key = 'release_date' if platform == 'x86' else f'{platform}_release_date'
                    rel_date = prod[rel_date_key]
                    entry += f"\n{' ' * (3 + len(' - '))}{self.PLATFORM[platform]}: {version} ({rel_date})"
            lst.append(entry)
        return lst

    def get_open_source_by_index(self, indices: IndexList) -> list[ProductInfo]:
        if self.data_list is None:
            return []
        return [p for p in self.data_list if p['_index'] in indices]


class Product(Products):

    def __init__(self, product: ProductInfo):
        super().__init__()
        self.product = product
        self.link = PROD_BASE_LINK + product['link']['url']['href']
        self.cache_file = CACHE_DIR / f"product-{product['id']}.html"

    def _get_data(self) -> bool:
        soup = BeautifulSoup(self._get_page_text(), 'html.parser')
        linklist_tags = soup.select(PROD_DOWNLOAD_CSS)
        if len(linklist_tags) != 1:
            return False
            # raise ValueError(f'Expected 1 link list, got {len(linklist_tags)}')
        self.data_list = {}
        for a in linklist_tags[0].find_all('a'):
            m = re.search(PROD_REGEXP, a['href'])
            if m:
                name = m.group(2)
                # For whatever reason, link URLs have a non-functional http schema
                link = m.group(1).replace('http:', 'https:')
                self.data_list[name] = link
        return len(self.data_list) != 0

    def get_data_list(self) -> DisplayList:
        if self.data_list is None:
            if not self._get_data():
                return []
        return list(self.data_list.keys())

    def download_kits_by_index(self, indices: IndexList) -> None:
        if self.data_list is None:
            return
        for i, name in enumerate(self.data_list.keys()):
            if i in indices:
                # print(f'Downloading {name} ', end='')
                # response = self.session.get(self.data_list[name], stream=True, verify=SSL_VERIFY)
                # response.raise_for_status()
                # with open(name, 'wb') as f:
                #     shutil.copyfileobj(response.raw, f)
                # print('- Done.')
                print(f'Downloading {name} ', flush=True)
                ssl._create_default_https_context = ssl._create_unverified_context  # noqa
                wget.download(self.data_list[name], name)


def parse_input(inp: str, max_idx: int) -> IndexList | None:
    if re.search(r'[^\d,-]', inp):
        return None
    indices = set()
    for entry in inp.split(','):
        if entry.isdigit():
            lo = hi = int(entry) - 1
        else:
            m = re.match(r'^(\d+)-(\d+)$', entry)
            if not m:
                return None
            lo = int(m.group(1)) - 1
            hi = int(m.group(2)) - 1
            if lo > hi:
                lo, hi = hi, lo
        if lo < 0 or hi >= max_idx:
            return None
        indices |= set(range(lo, hi + 1))
    return sorted(indices)


def display_and_select_from_list(entries: DisplayList, title: str) -> IndexList:
    if len(entries) == 0:
        print('\n' + title + ':')
        input('Error: Nothing to list. Press return to continue')
        return []
    all_entries = str(len(entries) + 1)
    while True:
        print('\n' + title + ':')
        for i, entry in enumerate(entries):
            print(f'{i+1:>3} - {entry}')
        print(f'{all_entries:>3} - All of the above')
        print(f"{'?':>3} - Help")
        print(f"{'E':>3} - Exit")

        response = input(f'Choose one or more items from the menu: ')
        response = re.sub(r'\s+', '', response)
        if response == '?':
            print(HELP_TEXT)
            input('Press return to continue')
            continue
        elif response.upper() == 'E':
            return []
        elif response == all_entries:
            return list(range(len(entries)))

        indices = parse_input(response, len(entries))
        if indices is None:
            input('Error: Invalid response. Press return to continue')
            continue
        return indices


def main():
    products = Products()
    prod_list = products.get_data_list()

    while True:
        prod_idx = display_and_select_from_list(prod_list, 'Open Source Products')
        if len(prod_idx) == 0:
            print('%fac-I-USERABORT, operation terminated by user request')
            break

        for prod in products.get_open_source_by_index(prod_idx):
            product = Product(prod)
            kit_list = product.get_data_list()
            kit_idx = display_and_select_from_list(kit_list, f"Downloadable kits for {prod['title']}")
            if len(kit_idx) == 0:
                continue
            product.download_kits_by_index(kit_idx)


if __name__ == '__main__':
    if not SSL_VERIFY:
        warnings.filterwarnings(action='ignore', message='Unverified HTTPS request is being made')
    if USE_CACHE and not CACHE_DIR.exists():
        CACHE_DIR.mkdir(parents=True)
    main()
