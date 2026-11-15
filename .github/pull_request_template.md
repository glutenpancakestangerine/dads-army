**What it changes**



**Getting it to everyone**

Merging a pull request that raises the version is the release: Home Assistant offers the update straight away. If it changes the app (anything in `dadsarmy/`):

- [ ] The version is raised in `dadsarmy/config.yaml` and `VERSION` in `dadsarmy/server.py`
- [ ] There's an entry for it at the top of `dadsarmy/CHANGELOG.md`, which Home Assistant shows in the update dialog
- [ ] The tests pass: `python3 -m unittest discover -s tests`

There's no need to add a tag: one is added once it's merged. Your name is added to the credits too. Thank you for helping.
