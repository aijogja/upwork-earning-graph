# upwork-earning-graph
About Upwork Earning Graph (https://upwork.aijogja.com)

## Requirements
- Python 3.12
- Django 4.2

## Development
- create virtualenv
- pip install -r requirements.txt
- create `.env` file
-  run server (LAN): `python3 manage.py runserver 192.168.0.138:8000`

## `.env` file
Here are the `.env` file
```
DEBUG=on
SECRET_KEY=secret
ALLOWED_HOSTS=
DATABASE_URL=psql://docker:docker@127.0.0.1:5432/upwork_earning_graph
UPWORK_PUBLIC_KEY=upwork-public-key
UPWORK_SECRET_KEY=upwork-secret-key
UPWORK_CALLBACK_URL=http://localhost:8000/callback/
```

Notes:
- `UPWORK_CALLBACK_URL` must exactly match the Redirect URI configured in your Upwork app (scheme/host/port/path, including the trailing slash).
- Start the OAuth flow from `http://<host>:8000/auth/` (so the `state` value is stored in the session).

## Contribution
To contribute, please setup in you local environment.

### Rules:
- Please follow our guideline [Karamel Style](https://github.com/KaramelDev/Karamel-Style-Guide-Standart/blob/master/BACKEND.md)
- Before run `git add`, please run following command `black .` to reformat the code standard pep8.
- We use pre-commit hooks to ensure code quality. Before committing your changes, please set up pre-commit:

  ```bash
  # Install pre-commit
  pip install pre-commit

  # Activate pre-commit hooks in the repository
  pre-commit install
  ```

- Pre-commit will automatically run Black and other checks before each commit. If any check fails, the commit will be aborted until you fix the issues.
- You can run pre-commit manually on all files:

  ```bash
  pre-commit run --all-files
  ```
