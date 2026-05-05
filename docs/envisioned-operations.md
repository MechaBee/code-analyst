# Envisioned operations

## User management
Simple user authentication. Users may belong to teams.
There are admin users who can create teams and manage team membership.

## Repositories

The system can manage multiple source repositories. Each repository has an endpoint and an app access profile allowing the system to perform actions on it. The access profiles are based off of the source repo kind: github (current), gitlab (future).
Each repository definition access can be allowed to one or more teams.

Respositories can be checked out from github (already implemented) and Gitlab (future). The app would have installed account / app to app service authentication profiles it can use to authenticate against repositories to perform actions (ie checkout, ticket actions, etc).

Checked out repository state is staged on s3 (or minio for testing) and wormspace state can be refreshed by a user having access to it via team membership.

Repo staged state is used to prime agent sandbox virtual env to perform question / answering sessions.

## User dashboard
- Header: profile, logout
- Left content:
    - Actions: import repository
    - List of recent conversations grouped by repository.
    - Add repository to user workspace.
- Main content:
    - agentic question answering over the selected repository.

## Admin dashboard
- Header: logout
- Main content:
    - list teams, add new team, add members to team, remove member from team. members / users (principals are represented by their email address)

# Entity notes:

All entities live under a tenant id.

Users belong to teams.

Repository definitions are associated with one or more teams. Repository definitions have an id to refer to.

Conversations should be scoped to principal email (the user having the conversation with the AI) and repository definition reference the conversation is about.

Workspaces belong to a repository and a checkout run. Checkouts have a branch and date/time it was run.

Sandboxes are born from a checkout and can be shared by multiple conversations. Sandboxes are not mutated by conversations.





# Technical notes:
- If required, use dynamodb for custom app state management when s3 is not best suited.
- Use S3 for conversation state, repo checkout state / workspaces
- Use cognito as user directory and simple authentication
- Use CDK for any required AWS resource provisioning / can initialize in this monorepo
