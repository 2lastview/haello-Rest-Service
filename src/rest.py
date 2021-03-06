#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2015 Moritz Tomasi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import web
import uuid
import logging
from PIL import Image
import pytesseract
import goslate
import json
import base64

LOGGER = logging.getLogger('rest')

urls = ('/enrich', 'Enrich')

supported_filetypes = ['jpg']

supported_languages = ['en', 'de', 'it']
supported_languages_tesseract = {'en': 'eng',
                                 'de': 'deu',
                                 'it': 'ita',
                                 'fr': 'fra',
                                 'es': 'spa',
                                 'sv': 'swe'}


class Enrich:
    """
    This class enriches an image by extracting text and then translating said text into a specified language.
    """

    def __init__(self):
        pass

    def GET(self):
        """
        This method is the first method that is called. It provides a form that makes uploading an image
        with POST possible.
        """

        LOGGER.info('GET in Enrich called.')

        return """<html><head></head><body>
            <form method="POST" enctype="multipart/form-data" action="">
            <input type="file" name="image" /><input type="submit" />
            </form></body></html>"""

    def POST(self):
        """
        image: the image that is supposed to be processed.
        text: the text that is supposed to be translated.
        source: the source language.
        target: the target language.
        filetype: filetype of the image.

        This method gets called on a POST request to /enrich. If the data contains text, then the image will not
        be used for operations. If the data contains an image it will be stored in a folder called uploads, using
        a uniquely identifying name. The first step is extracting text from the image. If there is no specified
        source language the application will try to extract the text, then detect the language in said text and then
        try to extract text for a second time. This is supposed to minimize errors made by the ocr engine.
        The extracted text is then translated to the specified target language. In a last step all the gathered
        information will be returned in form of a json.

        In case there is no image passed to the function, a bad request error (400) is raised.
        In case the an unsupported filetype is passed to the function, a bad request error (400) is raised.
        In case there is no filetype is passed to the function, a bad request error (400) is raised.
        In case the an unsupported target language is passed to the function, a bad request error (400) is raised.
        In case the passed image could not be stored, an internal server error (500) is raised.
        In case there is no target language passed to the function, a bad request error (400) is raised.

        :return: json with detected language, extracted text and translation of the extracted text.
        """

        LOGGER.info('POST in Enrich called.')

        text_from_image = None
        source_lang = None
        detected_lang = 'unk'

        corrected_text = None
        corrected = False

        data = web.input(image={})

        if 'text' in data:
            corrected_text = base64.b64decode(data.text)
            corrected = True

        if 'source' in data:
            source_lang = str(data.source).lower()

        if source_lang not in supported_languages:
            source_lang = None

        if 'image' in data and not corrected:
            image = data.image

            if len(image.value) == 0:
                LOGGER.debug('400 Bad Request: No image to process. No value.')
                raise web.badrequest(message='No image to process. No value.')

            if len(image.filename) == 0:
                LOGGER.debug('400 Bad Request: No image to process. No filename.')
                raise web.badrequest(message='No image to process. No filename.')

            if 'filetype' in data:
                filetype = str(data.filetype).lower()

                if filetype not in supported_filetypes:
                    LOGGER.debug('400 Bad Request: No support for this filetype.')
                    raise web.badrequest(message='No support for this filetype.')
            else:
                LOGGER.debug('400 Bad Request: No file-type specified.')
                raise web.badrequest(message='No file-type specified.')

            image_dir = 'uploads'
            image_id = str(uuid.uuid4())
            image_name = image_id + '.' + filetype

            try:
                out = open(image_dir + '/' + image_name, 'w')
                out.write(image.file.read())
                out.close()
            except:
                LOGGER.warning('500 Internal Server: Could not store image.')
                raise web.internalerror(message='Server: Could not store image.')
            finally:
                final_image_path = image_dir + '/' + image_name
                LOGGER.debug('Image saved in ' + image_dir + '/' + image_name)

                if source_lang is None:
                    text_from_image = self.get_text(final_image_path, None)
                else:
                    text_from_image = self.get_text(final_image_path, supported_languages_tesseract[source_lang])

                detected_lang = self.get_language(text_from_image)

                if source_lang is None and detected_lang in supported_languages_tesseract:
                    LOGGER.info('Image is read again with tesseract.')
                    text_from_image = self.get_text(final_image_path, supported_languages_tesseract[detected_lang])

                if detected_lang not in supported_languages:
                    detected_lang = self.get_language_name(detected_lang)

        if corrected:
            detected_lang = self.get_language(corrected_text)

            if detected_lang not in supported_languages:
                detected_lang = self.get_language_name(detected_lang)

        if 'target' in data:
            target_lang = str(data.target).lower()

            if target_lang not in supported_languages:
                LOGGER.debug('400 Bad Request: This target language is not supported.')
                raise web.badrequest(message='This target language is not supported.')

            if source_lang is None:
                if not corrected:
                    translation = self.get_translation(text_from_image, target_lang)
                else:
                    translation = self.get_translation(corrected_text, target_lang)
            else:
                if not corrected:
                    translation = self.get_translation(text_from_image, target_lang, source_lang)
                else:
                    translation = self.get_translation(corrected_text, target_lang, source_lang)

        else:
            LOGGER.debug('400 Bad Request: No language to translate into specified.')
            raise web.badrequest(message='No language to translate into specified.')

        if not corrected:
            return self.get_json(text_from_image, translation, detected_lang)
        else:
            return self.get_json(corrected_text, translation, detected_lang)

    @staticmethod
    def get_text(image_path, source_lang=None):
        """
        Static method that uses pytesseract to extract text from an image. The image is passed by specifying
        a file path. A source language can be specified. Note that pytesseract performs much better if a source
        language is passed.

        In case there is no image path passed to the function, an internal server error (500) is raised.
        In case the specified image cannot be opened, an internal server error (500) is raised.
        In case there is an error while extracting text with pytesseract, an internal server error (500) is raised.
        In case there was is no text that could be extracted from the image, a bad request error (404) is raised.

        :param image_path: path to the stored image.
        :param source_lang: the source language.
        :return: extracted text from the specified image.
        """

        LOGGER.info('get_text in Enrich called with parameters: image_path=' + image_path
                    + ' and source_lang=' + str(source_lang))

        if image_path is None or len(image_path) == 0:
            LOGGER.warning('500 Internal Server: Path to image is not valid.')
            raise web.internalerror(message='Path to image is not valid.')

        try:
            image = Image.open(image_path)
        except:
            LOGGER.warning('500 Internal Server: Could not open image.')
            raise web.internalerror(message='Could not open image.')

        try:
            if source_lang is None:
                text = pytesseract.image_to_string(image)
            else:
                text = pytesseract.image_to_string(image, source_lang)
        except:
            LOGGER.warning('500 Internal Server: Could not extract text from image.')
            raise web.internalerror(message='Could not extract text from image.')

        if len(text) <= 0:
            LOGGER.debug('404 Bad Request: No text detected in image.')
            raise web.notfound(message='No text detected in image.')

        LOGGER.debug('\n---------- Text ----------\n' + text + '\n---------- /Text ----------')
        return text

    @staticmethod
    def get_translation(text, target_lang, source_lang=None):
        """
        Static method that translates text using goslate. A source language can be specified. If that is not the case
        goslate will detect the source language automatically.

        In case there is no text passed to the function, an internal server error (500) is raised.
        In case there is no target language passed to the function, an internal server error (500) is raised.
        In case there is an error while translating text with goslate, an internal server error (500) is raised.

        :param text: the original text.
        :param target_lang: the target language (default None)
        :param source_lang: the source language.
        :return: translation of the text in the specified target language.
        """

        LOGGER.info('get_translation in Enrich called with text and parameters: target_lang=' + target_lang
                    + ' and source_lang=' + str(source_lang))

        gs = goslate.Goslate()

        if text is None or len(text) == 0:
            LOGGER.warning('500 Internal Server: No text specified.')
            raise web.internalerror(message='No text specified.')

        if target_lang is None or len(target_lang) == 0:
            LOGGER.warning('500 Internal Server: Target language is not valid.')
            raise web.internalerror(message='Target language is not valid.')

        try:
            if source_lang is None:
                translation = gs.translate(text, target_lang)
            else:
                translation = gs.translate(text, target_lang, source_lang)
        except:
            LOGGER.warning('500 Internal Server: Could not translate image.')
            raise web.internalerror(message='Could not translate image.')

        LOGGER.debug('\n---------- Translation ----------\n' + translation + '\n---------- /Translation ----------')
        return translation

    @staticmethod
    def get_language(text):
        """
        Static method that detects the source language of the specified text. The detected language is returned as an
        abbreviation.

        In case there is no text passed to the function, an internal server error (500) is raised.

        :param text: the original text used for language detection.
        :return: abbreviation of the detected language.
        """

        LOGGER.info('get_language in Enrich called with text.')

        gs = goslate.Goslate()

        if text is None or len(text) == 0:
            LOGGER.warning('500 Internal Server: No text specified.')
            raise web.internalerror(message='No text specified.')

        detected_lang = gs.detect(text)

        if detected_lang is None:
            detected_lang = 'unk'

        LOGGER.debug('Detected language: ' + detected_lang)
        return detected_lang

    @staticmethod
    def get_language_name(language):
        """
        Static method that transforms the abbreviation for a language returned by goslate into a plain text
        representation.

        In case there is no language passed to the function, an internal server error (500) is raised.

        :param language: language abbreviation.
        :return: language plain text representation.
        """

        gs = goslate.Goslate()

        LOGGER.info('get_language_name in Enrich called with language.')

        if language is None or len(language) == 0:
            LOGGER.warning('500 Internal Server: No language specified.')
            raise web.internalerror(message='No language specified.')

        gs_languages = gs.get_languages()
        detected_lang = 'Unknown'

        if language in gs_languages:
            detected_lang = 'detected:' + gs_languages[language]

        LOGGER.debug('Detected language: ' + detected_lang)
        return detected_lang

    @staticmethod
    def get_json(text, translation, detected_lang):
        """
        Combines all gathered information and returns it in form of a json.

        In case there is no text passed to the function, an internal server error (500) is raised.
        In case there is no translation passed to the function, an internal server error (500) is raised.
        In case there is no detected language passed to the function, an internal server error (500) is raised.

        :param text: the original text.
        :param translation: translation of the original text.
        :param detected_lang: the language that has been detected.
        :return: json representation of the data.
        """

        LOGGER.info('get_json in Enrich called with text, translation and parameters: detected_lang=' + detected_lang)

        if text is None or len(text) == 0:
            LOGGER.warning('500 Internal Server: No text specified.')
            raise web.internalerror(message='No text specified.')

        if translation is None or len(translation) == 0:
            LOGGER.warning('500 Internal Server: No translation specified.')
            raise web.internalerror(message='No translation specified.')

        if detected_lang is None or len(detected_lang) == 0:
            LOGGER.warning('500 Internal Server: Detected language is not valid.')
            raise web.internalerror(message='Detected language is not valid.')

        data = {
            'detected': detected_lang,
            'text': text,
            'translation': translation
        }

        return json.dumps(data)


def main():
    """
    Logger is configured so that the output is similar to the logging statements provided by web.py.
    A folder for uploads is created. This is where uploaded images will be stored.
    """

    logging.basicConfig(format='%(levelname)s - %(module)s - [%(asctime)s] "%(message)s"',
                        datefmt='%d/%h/%Y %H:%M:%S',
                        level=logging.DEBUG)

    LOGGER.info('Main called for CTE REST Server.')

    if not (os.path.isdir('uploads') and os.path.exists('uploads')):
        os.makedirs('uploads')

    app = web.application(urls, globals())
    app.run()

    LOGGER.info('REST Server for CTE shut down.')


if __name__ == '__main__':
    main()