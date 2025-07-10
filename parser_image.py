import pandas as pd
import requests
from bs4 import BeautifulSoup

def get_first_image_url(article):
    """
    Возвращает прямую ссылку на первое фото товара Wildberries по артикулу (nmId).
    Исправленный алгоритм на основе реальных примеров.
    """
    try:
        nm_id = int(article)
    except ValueError:
        return None

    vol = nm_id // 100000
    part = nm_id // 1000  # Исправлено: без умножения на 1000!

    # Определение номера basket по диапазонам vol
    if vol >= 0 and vol <= 143:
        host = "01"
    elif vol >= 144 and vol <= 287:
        host = "02"
    elif vol >= 288 and vol <= 431:
        host = "03"
    elif vol >= 432 and vol <= 719:
        host = "04"
    elif vol >= 720 and vol <= 1007:
        host = "05"
    elif vol >= 1008 and vol <= 1061:
        host = "06"
    elif vol >= 1062 and vol <= 1115:
        host = "07"
    elif vol >= 1116 and vol <= 1169:
        host = "08"
    elif vol >= 1170 and vol <= 1313:
        host = "09"
    elif vol >= 1314 and vol <= 1601:
        host = "10"
    elif vol >= 1602 and vol <= 1655:
        host = "11"
    elif vol >= 1656 and vol <= 1919:
        host = "12"
    elif vol >= 1920 and vol <= 2045:
        host = "13"
    elif vol >= 2046 and vol <= 2189:
        host = "14"
    elif vol >= 2190 and vol <= 2405:
        host = "15"
    elif vol >= 2406 and vol <= 2621:
        host = "16"
    elif vol >= 2622 and vol <= 2837:
        host = "17"
    elif 2838 <= vol <= 3083:
        host = "19"
    elif 3084 <= vol <= 3330:
        host = "20"
    else:
        host = "18"

    # Используем wbbasket.ru (как в вашем примере) и webp формат
    url = f"https://basket-{host}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/big/1.webp"
    return url




def update_excel_with_images(file_path):
    df = pd.read_excel(file_path)
    image_urls = []
    for article in df['WB Article']:
        if pd.isna(article):
            image_urls.append(None)
            continue
        url = get_first_image_url(article)
        image_urls.append(url)
        print(f"Артикул {article}: изображение {url}")
    df['Фото WB'] = image_urls  # Добавляем новый столбец с URL фото
    df.to_excel(file_path, index=False)
    print(f"Файл обновлен и сохранен: {file_path}")

if __name__ == "__main__":
    excel_file = "Tablitsa_bez_povtoriaiushchikhsia_kombinatsii.xlsx"
    update_excel_with_images(excel_file)
