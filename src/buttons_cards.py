import localization_strings as ls
import copy

def wrap_form(form):
    card = copy.deepcopy(EMPTY_CARD)
    card["content"] = form
    
    return card
    
def empty_form():
    return copy.deepcopy(EMPTY_FORM)

def nested_replace(structure, original, new):
    """replace {{original}} wrapped strings with new value
    use recursion to walk the whole sructure
    
    arguments:
    structure -- input dict / list / string
    original -- string to search for
    new -- will replace every occurence of {{original}}
    """
    if type(structure) == list:
        return [nested_replace( item, original, new) for item in structure]

    if type(structure) == dict:
        return {key : nested_replace(value, original, new)
                     for key, value in structure.items() }

    if type(structure) == str:
        return structure.replace("{{"+original+"}}", str(new))
    else:
        return structure
        
def nested_replace_dict(structure, replace_dict):
    """replace multiple {{original}} wrapped strings with new value
    use recursion to walk the whole sructure
    
    arguments:
    structure -- input dict / list / string
    replace_dict -- dict where key matches the {{original}} and value provides the replacement
    """
    for (key, value) in replace_dict.items():
        structure = nested_replace(structure, key, value)
        
    return structure

# form = bc.nested_replace_dict(bc.localize(bc.USER_WARNING_FORM, options["language"]), {"display_name": display_name, "email": event.data.personEmail, "group_name": team_info.name, "url_idm": os.getenv("URL_IDM"), "url_idm_guide": os.getenv("URL_IDM_GUIDE")})
def localize(structure, language):
    """localize structure using {{original}} wrapped strings with new value
    use recursion to walk the whole sructure
    
    arguments:
    structure -- input dict / list / string
    language -- language code which is used to match key in ls.LOCALES dict
    """
    if not language in ls.LOCALES.keys():
        return structure
        
    lang_dict = ls.LOCALES[language]
    return nested_replace_dict(structure, lang_dict)

# wrapper structure for Webex attachments list        
EMPTY_CARD = {
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": None,
}

EMPTY_FORM = {
    "type": "AdaptiveCard",
    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
    "version": "1.2",
    "body": []
}
