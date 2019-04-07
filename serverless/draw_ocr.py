import logging
import json
import csv
import os
import boto3

import pytesseract
from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger()
logger.setLevel(logging.INFO)


def decode_punycode(punycode_domain):
    """
    decodes a punycode 'xn--' domain into regular utf-8
    returns u
    """
    try:
        domain = punycode_domain.encode('utf-8').decode('idna')
    except UnicodeError as e:
        domain = e.args[2].decode('utf-8')

    return domain


def draw(domain, font, font_size=14):
    """
    draw the text with a given font and size,
    returns image as a Image object
    """
    logger.info(f"Drawing image for {domain}")

    image = Image.new("RGBA", (3000, 50), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    font = ImageFont.truetype(f"fonts/{font}.ttf", font_size)
    draw.text((10, 0), domain, (0, 0, 0), font=font)
    return image


def ocr(image):
    """
    ocr's the first line on a given image
    returns the confidence and output as a tuple
    """
    data = pytesseract.image_to_data(image, lang="eng")
    rows = data.split('\n')
    for row in rows[1:]:
        result = row.split('\t')
        if int(result[10]) > 0:
            return result[10], result[11]

    return 'n/a', 'n/a'


def draw_and_ocr(punycode_domain):

    setting = {"font": "DejaVuSans-Bold", "size": 42}

    domain = decode_punycode(punycode_domain)

    image = draw(domain, setting['font'], setting['size'])
    data = ocr(image)

    result = {"punycode_domain": punycode_domain,
              "decoded_domain": domain,
              "ocr": data[1],
              "confidence": data[0]}

    return result


def main(event, context):

    """
    draws out text from utf-8 string onto a RGBA image
    then ocrs that image using tesseract back to text using a trained english model
    output will be what an english speaker would guess it to be
    """

    # retrieve que message
    try:
        domains = json.loads(event['Records'][0]['body'])
        message_id = event['Records'][0]['messageId']
    except json.JSONDecodeError:
        logger.info("JSON Decoder error for event: {}".format(event))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry
    except KeyError:
        logger.info("Missing argument in que message")
        logger.info("Message dump: {}".format(json.dumps(event)))
        return {'status': 500}  # return 'successfully' to SQS to prevent retry

    logger.info(f'Drawing and processing {len(domains)} domains')
    results = [draw_and_ocr(domain) for domain in domains]

    logger.info('Saving output to csv file')
    filename = '/tmp/uuid.csv'
    with open(filename, 'w') as csvfile:
        fieldnames = ['punycode_domain', 'decoded_domain', 'ocr', 'confidence']
        csv_writer = csv.DictWriter(csvfile, delimiter=',', fieldnames=fieldnames)
        csv_writer.writerows(results)

    logger.info(f"Uploading csv file to {os.environ['ocr_bucket_name']}")
    s3 = boto3.resource('s3')
    s3.meta.client.upload_file(filename, os.environ['ocr_bucket_name'], message_id)

    return results




