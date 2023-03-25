# upwork-earning-graph
About Upwork Earning Graph (http://upwork.aijogja.com)

## Requirements
- Python 3.9
- Django 2.2

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
