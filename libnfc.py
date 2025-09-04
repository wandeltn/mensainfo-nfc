import nfc
import requests

url = "mensacheck.n-s-w.info"

payload = 'eingabe=6AD435A2'
headers = {
    'Content-Type': 'application/x-www-form-urlencoded'
}

clf = nfc.ContactlessFrontend('usb')

def read_tag(tag):
    print(tag.identifier.hex().upper())
    tag_id = tag.identifier.hex().upper()
    if check_tag_validity(tag_id):
        print("Tag is valid")
    else:
        print("Tag is not valid")



def check_tag_validity(tag: str) -> bool:
    response = requests.request("POST", url, headers=headers, data=payload)
    print(response.text)
    if "Erfolgreich gespeichert!" not in response.text:
        return False
    return True

while True:
    clf.connect(rdwr={'on-connect': read_tag})
    # Exit on user command
    if input("Type 'exit' to quit: ").strip().lower() == 'exit':
        break

clf.close()


