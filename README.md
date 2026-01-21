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
