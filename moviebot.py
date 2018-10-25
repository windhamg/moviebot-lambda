"""
 This code sample demonstrates an implementation of the Lex Code Hook Interface
 in order to serve a bot which allows users to get movie times, locations and information.
"""

import json
import os
import re
import arrow
import logging
import requests
from difflib import SequenceMatcher
from pprint import pprint

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


""" --- Helpers to build responses which match the structure of the necessary dialog actions --- """


def elicit_slot(session_attributes, intent_name, slots, slot_to_elicit, message=None, response_card=None):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ElicitSlot',
            'intentName': intent_name,
            'slots': slots,
            'slotToElicit': slot_to_elicit
        }
    }
    if message:
        response['dialogAction']['message'] = message
    if response_card:
        response['dialogAction']['responseCard'] = response_card

    return response


def elicit_intent(session_attributes, intent_name, message=None, response_card=None):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ElicitIntent'
        }
    }
    if message:
        response['dialogAction']['message'] = message
    if response_card:
        response['dialogAction']['responseCard'] = response_card

    return response


def confirm_intent(session_attributes, intent_name, slots, message=None, response_card=None):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ConfirmIntent',
            'intentName': intent_name,
            'slots': slots
        }
    }
    if message:
        response['dialogAction']['message'] = message
    if response_card:
        response['dialogAction']['responseCard'] = response_card

    return response


def close(session_attributes, fulfillment_state, message):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Close',
            'fulfillmentState': fulfillment_state,
            'message': message
        }
    }

    return response


def delegate(session_attributes, slots):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Delegate',
            'slots': slots
        }
    }


def build_response_card(title, subtitle, options):
    """
    Build one or more responseCards with a title, subtitle, and an optional set of options which should be displayed as buttons.
    """
    attachments = []
    # Lex permits max 5 buttons per card
    cnt = int(len(options) / 5)
    if (len(options) % 5) > 0:
        cnt = cnt + 1
    for i in range(0, cnt):
        start = i*5
        end = (i+1)*5
        group = options[start:end]
        buttons = None
        if group is not None:
            card_title = title
            buttons = []
            for j in range(min(5, len(group))):
                buttons.append(group[j])
            if cnt > 1:
                card_title = "%s - page %d" % (card_title, i+1)
            attachments.append({
                'title': card_title,
                'subTitle': subtitle,
                'buttons': buttons
            })
    return {
        'contentType': 'application/vnd.amazonaws.card.generic',
        'version': 1,
        'genericAttachments': attachments
    }


""" --- Helper Functions --- """


def similar(a, b):
    """
    Help function which returns probability if 2 strings are similar (using difflib)
    """
    return SequenceMatcher(None, a, b).ratio()


def build_validation_result(is_valid, violated_slot, message_content):
    return {
        'isValid': is_valid,
        'violatedSlot': violated_slot,
        'message': {'contentType': 'PlainText', 'content': message_content}
    }


def validate_zipcode(slots, output_session_attributes):
    # check if zipcode in session attrs or request slots, and if it is valid
    zipcode = None
    if not output_session_attributes:
        output_session_attributes = {}
    if 'zipcode' in slots and slots['zipcode']:
        zipcode = slots['zipcode']
    elif output_session_attributes and 'zipcode' in output_session_attributes:
        zipcode = output_session_attributes['zipcode']
    if zipcode:
        # check format of zipcode
        zipcode_match = re.search('^(\d{5})([- ])?(\d{4})?$', zipcode)
        if zipcode_match:
            zipcode = zipcode_match.group(1)
            output_session_attributes['zipcode'] = zipcode
        else:
            zipcode = False
    return [zipcode, output_session_attributes]


""" --- Functions that control the bot's behavior --- """


def help(intent_request):
    """
    Returns help information and examples for bot
    """
    examples = [
        "  * What movies are out right now?",
        "  * What movies are playing near _zipcode_?",
        "  * Where is _movie_ playing?",
        "  * Tell me when _movie_ is showing at _theater_",
        "  * How long is _movie_?",
        "  * What is _movie_ rated?"
    ]
    output_session_attributes = intent_request['sessionAttributes']
    content = "You can ask me for information about when and where movies are playing, as well as for basic info on current movies. Here are some examples of things you can ask me:\n%s" % "\n".join(examples)
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )

def get_movie_detail(intent_request):
    """
    Performs dialog management and fulfillment for retrieving info
    for a particular movie.
    """
    movie_title = intent_request['currentIntent']['slots']['movie_title']
    source = intent_request['invocationSource']
    output_session_attributes = intent_request['sessionAttributes']
    rating = ''
    release_date = ''
    runtime = 0

    # get TMDB movie ID based on provided movie title
    best_id = 0
    best_title = ''
    r = requests.get('https://api.themoviedb.org/3/search/movie', params={'language': 'en-US', 'page': '1', 'include_adult': 'false', 'primary_release_year': '2018', 'query': movie_title.strip(), 'api_key': os.environ['TMDB_API_KEY']})
    if r.status_code == 200 and r.text:
        results = r.json()
        best_sim = 0
        # find closest match to provided movie title
        for m in results['results']:
            prob = similar(m['title'].lower().strip(), movie_title.lower().strip())
            if prob >= 0.5:
                if prob > best_sim:
                    best_sim = prob
                    best_id = m['id']
                    best_title = m['title']
    if best_id != 0:
        # get movie rating
        r = requests.get("https://api.themoviedb.org/3/movie/%s/release_dates" % best_id, params={'api_key': os.environ['TMDB_API_KEY']})
        if r.status_code == 200 and r.text:
            results = r.json()
            for r in results['results']:
                if r['iso_3166_1'] == 'US':
                    rating = r['release_dates'][0]['certification']

        # get movie runtime and release date
        r = requests.get("https://api.themoviedb.org/3/movie/%s" % best_id, params={'api_key': os.environ['TMDB_API_KEY'], 'language': 'en-US'})
        if r.status_code == 200 and r.text:
            result = r.json()
            runtime = result['runtime']
            release_date = arrow.get(result['release_date']).format('ddd, MMM Do YYYY')

    if best_id:
        content = "Here is some info for *%s*:\n_Release date_: %s\n_Runtime_: %d mins\n_Rating_: %s" % (best_title, release_date, runtime, rating)
    else:
        content = "I'm sorry, I can't find any info for *%s*" % movie_title
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )


def get_showtimes(intent_request):
    """
    Performs dialog management and fulfillment for finding showtimes for a
    (movie, theater) pair.
    """
    source = intent_request['invocationSource']
    slots = intent_request['currentIntent']['slots']
    output_session_attributes = intent_request['sessionAttributes']

    # perform slot validation
    if source == 'DialogCodeHook':
        zipcode, output_session_attributes = validate_zipcode(slots, output_session_attributes)
        if not zipcode:
            if zipcode == False:
                # user entered improperly-formatted zipcode -- need to correct
                return build_validation_result(False, 'zipcode', 'Whoops! You entered an invalid zip code. What is your zip code?')
            # prompt for zipcode
            return elicit_slot(
                output_session_attributes,
                intent_request['currentIntent']['name'],
                slots,
                'zipcode'
            )
        else:
            # delegate control back to Lex to perform intent fulfillment
            return delegate(output_session_attributes, slots)

    movie_title = slots['movie_title']
    theater_name = slots['theater_name']
    zipcode = output_session_attributes['zipcode']

    # send API request to get movie info
    start_date = arrow.utcnow().to('-07:00').format('YYYY-MM-DD')
    r = requests.get('http://data.tmsapi.com/v1.1/movies/showings', params={'startDate': start_date, 'zip': zipcode, 'numDays': 3, 'api_key': os.environ['TMS_API_KEY']})
    if r.status_code == 200 and r.text:
        movies = r.json()
        best_sim = 0
        best_title = ''
        best_theater = ''
        # find closest match to provided movie title
        for m in movies:
            prob = similar(m['title'].lower().strip(), movie_title.lower().strip())
            if prob >= 0.5:
                if prob > best_sim:
                    best_sim = prob
                    best_title = m['title']
        best_sim = 0
        # find closest match to provided theater name
        for m in movies:
            for s in m['showtimes']:
                prob = similar(s['theatre']['name'].lower().strip(), theater_name.lower().strip())
                if prob >= 0.5:
                    if prob > best_sim:
                        best_sim = prob
                        best_theater = s['theatre']['name']
        showtimes = []
        # find showings of movies matching our best-guessed movie playing
        # at our best-guessed theater
        for m in movies:
            if m['title'] == best_title:
                for s in m['showtimes']:
                    if s['theatre']['name'] == best_theater:
                        showtimes.append(arrow.get(s['dateTime'], 'YYYY-MM-DDTHH:mm').format('ddd, MMM Do @ h:mm a'))

    if len(showtimes) > 0:
        showtimes_list = "\n".join(["* %s" % t for t in showtimes])
        content = "*%s* is showing at %s at the following times:\n```%s```" % (best_title, best_theater, showtimes_list)
    else:
        content = "I'm sorry, I can't find any showtimes for *%s* at %s" % (best_title, best_theater)
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )


def find_movie(intent_request):
    """
    Performs dialog management and fulfillment for finding a particular movie
    playing in a zip code area.
    """
    source = intent_request['invocationSource']
    slots = intent_request['currentIntent']['slots']
    output_session_attributes = intent_request['sessionAttributes']

    # perform slot validation
    if source == 'DialogCodeHook':
        zipcode, output_session_attributes = validate_zipcode(slots, output_session_attributes)
        if not zipcode:
            if zipcode == False:
                # user entered improperly-formatted zipcode -- need to correct
                return build_validation_result(False, 'zipcode', 'Whoops! You entered an invalid zip code. What is your zip code?')
            # prompt for zipcode
            return elicit_slot(
                output_session_attributes,
                intent_request['currentIntent']['name'],
                slots,
                'zipcode'
            )
        else:
            # delegate control back to Lex to perform intent fulfillment
            return delegate(output_session_attributes, slots)

    movie_title = slots['movie_title']
    zipcode = output_session_attributes['zipcode']

    # send API request to get movie info
    theaters = []
    start_date = arrow.utcnow().to('-07:00').format('YYYY-MM-DD')
    r = requests.get('http://data.tmsapi.com/v1.1/movies/showings', params={'startDate': start_date, 'zip': zipcode, 'api_key': os.environ['TMS_API_KEY']})
    if r.status_code == 200 and r.text:
        movies = r.json()
        best_sim = 0
        best_title = ''
        # find closest match to provided movie title
        for m in movies:
            prob = similar(m['title'].lower().strip(), movie_title.lower().strip())
            if prob >= 0.5:
                if prob > best_sim:
                    best_sim = prob
                    best_title = m['title']
        # find all theaters showing our best-matched title
        for m in movies:
            if m['title'] == best_title:
                for s in m['showtimes']:
                    if s['theatre']['name'] in theaters:
                        continue
                    else:
                        theaters.append(s['theatre']['name'])
    if len(theaters) > 0:
        theater_opts = []
        for t in theaters:
            theater_opts.append({
                'text': t,
                'value': 'When is theater %s showing film %s' % (t, best_title)
            })
        return elicit_intent(
            output_session_attributes,
            'FindShowtimes',
            {'contentType': 'PlainText', 'content': '*%s* is showing at the following theaters:' % best_title},
            build_response_card(
                'Theaters showing %s' % best_title,
                'Select a theater to see showtimes',
                theater_opts
            )
        )
    else:
        content = "I'm sorry, I can't find any theaters showing *%s*" % movie_title
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )


def get_theater_movies(intent_request):
    """
    Performs dialog management and fulfillment for finding movies playing at a
    particular theater in a zip code area.
    """
    source = intent_request['invocationSource']
    slots = intent_request['currentIntent']['slots']
    output_session_attributes = intent_request['sessionAttributes']

    # perform slot validation
    if source == 'DialogCodeHook':
        zipcode, output_session_attributes = validate_zipcode(slots, output_session_attributes)
        if not zipcode:
            if zipcode == False:
                # user entered improperly-formatted zipcode -- need to correct
                return build_validation_result(False, 'zipcode', 'Whoops! You entered an invalid zip code. What is your zip code?')
            # prompt for zipcode
            return elicit_slot(
                output_session_attributes,
                intent_request['currentIntent']['name'],
                slots,
                'zipcode'
            )
        else:
            # delegate control back to Lex to perform intent fulfillment
            return delegate(output_session_attributes, slots)

    theater_name = slots['theater_name']
    zipcode = output_session_attributes['zipcode']

    # send API request to get movie info
    movies_list = []
    start_date = arrow.utcnow().to('-07:00').format('YYYY-MM-DD')
    r = requests.get('http://data.tmsapi.com/v1.1/movies/showings', params={'startDate': start_date, 'zip': zipcode, 'api_key': os.environ['TMS_API_KEY']})
    if r.status_code == 200 and r.text:
        movies = r.json()
        prob = 0
        best_sim = 0
        best_theater = ''
        # determine best theater name match
        for m in movies:
            for s in m['showtimes']:
                prob = similar(s['theatre']['name'].lower().strip(), theater_name.lower().strip())
                if prob >= 0.5:
                    if prob > best_sim:
                        best_sim = prob
                        best_theater = s['theatre']['name']
        # find movies at best-matched theater name
        for m in movies:
            for s in m['showtimes']:
                if s['theatre']['name'] == best_theater:
                    if m['title'] in movies_list:
                        continue
                    else:
                        movies_list.append(m['title'])
    if len(movies_list) > 0:
        movie_opts = []
        for m in movies_list:
            movie_opts.append({
                'text': m,
                'value': 'When is theater %s showing film %s' % (best_theater, m)
            })
        return elicit_intent(
            output_session_attributes,
            'FindShowtimes',
            {'contentType': 'PlainText', 'content': 'Currently showing at *%s*:' % best_theater},
            build_response_card(
                'Now showing',
                'Select a movie to see showtimes',
                movie_opts
            )
        )
    else:
        content = "I'm sorry, I can't find any movies showing at *%s*" % theater_name
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )


def get_movies(intent_request):
    """
    Performs dialog management and fulfillment for listing all movies playing in
    a zip code area.
    """
    source = intent_request['invocationSource']
    slots = intent_request['currentIntent']['slots']
    output_session_attributes = intent_request['sessionAttributes']

    # perform slot validation
    if source == 'DialogCodeHook':
        zipcode, output_session_attributes = validate_zipcode(slots, output_session_attributes)
        if not zipcode:
            if zipcode == False:
                # user entered improperly-formatted zipcode -- need to correct
                return build_validation_result(False, 'zipcode', 'Whoops! You entered an invalid zip code. What is your zip code?')
            # prompt for zipcode
            return elicit_slot(
                output_session_attributes,
                intent_request['currentIntent']['name'],
                slots,
                'zipcode'
            )
        else:
            # delegate control back to Lex to perform intent fulfillment
            return delegate(output_session_attributes, slots)


    # send API request to get movie showings
    zipcode = output_session_attributes['zipcode']
    movies_list = []
    start_date = arrow.utcnow().to('-07:00').format('YYYY-MM-DD')
    r = requests.get('http://data.tmsapi.com/v1.1/movies/showings', params={'startDate': start_date, 'zip': zipcode, 'api_key': os.environ['TMS_API_KEY']})
    if r.status_code == 200 and r.text:
        movies = r.json()
        for m in movies:
            if m['title'] in movies_list:
                continue
            else:
                movies_list.append(m['title'])
    if len(movies_list) > 0:
        movie_opts = []
        for m in movies_list:
            movie_opts.append({
                'text': m,
                'value': 'Where is the film %s playing near %s' % (m, zipcode)
            })
        return elicit_intent(
            output_session_attributes,
            'FindMovie',
            {'contentType': 'PlainText', 'content': 'Here are the movies I found:'},
            build_response_card(
                'Movies showing near %s' % zipcode,
                'Select a movie to see theaters',
                movie_opts
            )
        )
    else:
        content = "I'm sorry, I can't find any movies showing near *%s*" % zipcode
    return close(
        output_session_attributes,
        'Fulfilled',
        {
            'contentType': 'PlainText',
            'content': content
        }
    )


""" --- Intents --- """


def dispatch(intent_request):
    """
    Called when the user specifies an intent for this bot.
    """

    logger.debug('dispatch userId={}, intentName={}'.format(intent_request['userId'], intent_request['currentIntent']['name']))

    intent_name = intent_request['currentIntent']['name']

    # Dispatch to your bot's intent handlers
    if intent_name == 'FindMovie':
        return find_movie(intent_request)
    if intent_name == 'GetTheaterMovies':
        return get_theater_movies(intent_request)
    if intent_name == 'GetMovies':
        return get_movies(intent_request)
    if intent_name == 'FindShowtimes':
        return get_showtimes(intent_request)
    if intent_name == 'GetMovieDetail':
        return get_movie_detail(intent_request)
    if intent_name == 'GetHelp':
        return help(intent_request)
    raise Exception('Intent with name ' + intent_name + ' not supported')


""" --- Main handler --- """


def lambda_handler(event, context):
    """
    Route the incoming request based on intent.
    The JSON body of the request is provided in the event slot.
    """

    logger.debug('event.bot.name={}'.format(event['bot']['name']))
    pprint(event)
    return dispatch(event)
