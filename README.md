# upwork-earning-graph
About Upwork Earning Graph (https://upwork.aijogja.com)

## Requirements
- Python 3.10
- Django 4.2

## Development
- create virtualenv
- pip install -r requirements.txt
- create `.env` file

## `.env` file
Here are the `.env` file
```
DEBUG=on
SECRET_KEY=secret
ALLOWED_HOSTS=*
DATABASE_URL=psql://docker:docker@127.0.0.1:5432/upwork_earning_graph
UPWORK_PUBLIC_KEY=upwork-public-key
UPWORK_SECRET_KEY=upwork-secret-key
```

## Contribution
To contribute, please setup in you local environment.

Rules:
- Please follow our guideline [Karamel Style](https://github.com/KaramelDev/Karamel-Style-Guide-Standart/blob/master/BACKEND.md)
- Before run `git add`, please run following command `black .` to reformat the code standard pep8.
