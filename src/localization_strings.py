from unidecode import unidecode

# form = bc.nested_replace_dict(bc.localize(bc.USER_WARNING_FORM, options["language"]), {"display_name": display_name, "email": event.data.personEmail, "group_name": team_info.name, "url_idm": os.getenv("URL_IDM"), "url_idm_guide": os.getenv("URL_IDM_GUIDE")})

# language list which is presented in settings
LANGUAGES = {
    "cs_CZ": "Čeština",
    "en_US": "English"
}

def lang_list_for_card():
    lan_list = []
    for (key, value) in LANGUAGES.items():
        lan_list.append({"title": value, "value": key})
        
    lan_list.sort(key=lambda x: unidecode(x["title"]).lower())
    
    return lan_list

# each language has to have its own constant here
CS_CZ = {
    "loc_default_form_msg": "Toto je formulář. Zobrazíte si ho v aplikaci nebo webovém klientovi Webex."
}

EN_US = {
    "loc_default_form_msg": "This is a form. It can be displayed in a Webex app or web client."
}

# add the  language constant to make it available for the Bot
LOCALES = {
    "cs_CZ": CS_CZ,
    "en_US": EN_US
}
