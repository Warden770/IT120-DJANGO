# Submission checklist (deadline: November 16, 2026)

- [ ] App runs: `python manage.py migrate` then `python manage.py runserver`
- [ ] `python manage.py test` passes
- [ ] Manual test table in `README.md` filled in with real results
- [ ] Member names filled in `README.md`
- [ ] `.env` is **not** in the repository (`git ls-files | findstr .env` shows only `.env.example`)
- [ ] No API key/token visible anywhere in the code, screenshots or video
- [ ] GitHub repo contains code, templates, static files, `requirements.txt`, `README.md`
- [ ] Repo is accessible to the instructor (public, or invite the instructor)
- [ ] Commit history shows work from all 3 members (each member commits from their own account)
- [ ] Demo video is 3–10 minutes and playable through the link / attachment
- [ ] Email sent to **joshuatubo4@gmail.com**
- [ ] Email subject is exactly: `Assignment_IT 120-1stSemSY26-27`
- [ ] Email contains the GitHub link and the video (attached or accessible link)
- [ ] Added the group members to the class spreadsheet and ticked the box

## Email template

**To:** joshuatubo4@gmail.com
**Subject:** Assignment_IT 120-1stSemSY26-27

Dear Instructor,

We are submitting our group assignment, *Build a Django Application for Sending SMS*.

Group Members:
1. [Member 1]
2. [Member 2]
3. [Member 3]

GitHub Repository: [link]
Demonstration Video: [attach the video or insert an accessible link]

Thank you.

Respectfully,
[Group Representative]

## Suggested Git workflow for the team

```bash
git init
git add .
git commit -m "Initial Django SMS project"
git branch -M main
git remote add origin https://github.com/<group-account>/<repo>.git
git push -u origin main
```

Each member: `git checkout -b feature/<your-part>`, commit your own files, push, and open a pull request.
Small, descriptive commits from every member are what the "commit history and collaboration" criterion looks at.
