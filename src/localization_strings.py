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
    "loc_default_form_msg": "Toto je formulář. Zobrazíte si ho v aplikaci nebo webovém klientovi Webex.",
    "loc_recording_expires": "Stažení je možné do {}",
    "loc_invalid_meeting": "Neplatné číslo schůzky",
    "loc_unable_to_get_meeting": "Schůzka neexistuje nebo k ní nelze získat přístup.",
    "loc_help": "Pro získání nahrávek napište číslo schůzky",
    "loc_pmr_owner": "K nahrávkám v Osobní místnosti má přístup pouze její majitel.",
    "loc_host_only": "K nahrávkám má přístup pouze hostitel schůzky.",
    "loc_meeting_number": "Zadejte, prosím, číslo schůzky.",
    "loc_click": "Klikněte na tlačítko",
    "loc_submit": "OK",
    "loc_meeting_no": "Číslo schůzky",
    "loc_meeting_host": "Hostitel",
    "loc_days": "Dní zpět"
}

EN_US = {
    "loc_default_form_msg": "This is a form. It can be displayed in a Webex app or web client.",
    "loc_recording_expires": "Download available until {}",
    "loc_invalid_meeting":  "Invalid meeting number.",
    "loc_unable_to_get_meeting": "Unable or not allowed to get the meeting information.",
    "loc_help": "Provide meeting number to get its recordings",
    "loc_pmr_owner": "Only owner can request a PMR meeting recording.",
    "loc_host_only": "Only host can request a meeting recording.",
    "loc_meeting_number": "Please provide a meeting number.",
    "loc_click": "Click on a button",
    "loc_submit": "Submit",
    "loc_meeting_no": "Meeting number",
    "loc_meeting_host": "Meeting host",
    "loc_days": "Days back"
}

# add the  language constant to make it available for the Bot
LOCALES = {
    "cs_CZ": CS_CZ,
    "en_US": EN_US
}
