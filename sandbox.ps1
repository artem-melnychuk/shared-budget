<#
Run Claude Code unattended on a clone of this repo, inside Docker.

  .\sandbox.ps1            start the sandbox and open Claude Code (no permission prompts)
  .\sandbox.ps1 shell      bash inside the agent container
  .\sandbox.ps1 check      smoke test: identity, tests, credentials, network
  .\sandbox.ps1 review     fetch the agent's branch into this repo and list what it changed
  .\sandbox.ps1 publish    review, then (after a y/N prompt) merge agent into master and push to GitHub
  .\sandbox.ps1 update     merge this repo's master into the agent's branch
  .\sandbox.ps1 rebuild    rebuild the images after editing .sandbox\
  .\sandbox.ps1 down       stop and remove the containers (the Claude login volume stays)

The agent works in ..\shared_budget_sandbox on branch "agent" and has no way
to push. Nothing it does reaches master or GitHub until you take it here.
#>
param(
    [ValidateSet('claude', 'shell', 'check', 'review', 'publish', 'update', 'rebuild', 'down')]
    [string]$Command = 'claude'
)

$Repo = $PSScriptRoot
$Sandbox = Join-Path (Split-Path $Repo -Parent) 'shared_budget_sandbox'
$ComposeFile = Join-Path $Repo '.sandbox\compose.yaml'

function Assert-Ok([string]$What) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$What failed (exit code $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
}

function Initialize-Clone {
    if (Test-Path (Join-Path $Sandbox '.git')) { return }
    Write-Host "Creating the agent's clone at $Sandbox"
    git clone --quiet --config core.autocrlf=false $Repo $Sandbox
    Assert-Ok 'git clone'
    git -C $Sandbox switch --quiet -c agent
    Assert-Ok 'git switch -c agent'
}

function Start-Sandbox {
    Initialize-Clone
    docker compose -f $ComposeFile up -d
    Assert-Ok 'docker compose up'
}

# Fetches the agent's branch into this repo as "agent"; returns its commits that master lacks.
function Show-AgentWork {
    git -C $Repo fetch --quiet $Sandbox agent:agent
    Assert-Ok 'git fetch agent'
    $commits = git -C $Repo log --oneline master..agent
    if (-not $commits) {
        Write-Host "No new commits on agent."
        return $null
    }
    Write-Host "Commits on agent that master does not have:"
    $commits | ForEach-Object { Write-Host "  $_" }
    git -C $Repo --no-pager diff --stat master...agent | Out-Host
    Write-Host "Full diff:  git diff master...agent"
    return $commits
}

switch ($Command) {
    'claude' {
        Start-Sandbox
        docker compose -f $ComposeFile exec agent claude --dangerously-skip-permissions
    }
    'shell' {
        Start-Sandbox
        docker compose -f $ComposeFile exec agent bash -l
    }
    'check' {
        Start-Sandbox
        docker compose -f $ComposeFile exec agent /opt/check.sh
    }
    'review' {
        Show-AgentWork | Out-Null
    }
    'publish' {
        $current = git -C $Repo branch --show-current
        if ($current -ne 'master') {
            Write-Host "Switch this repo to master first (it is on $current)." -ForegroundColor Red
            exit 1
        }
        if (Show-AgentWork) {
            $answer = Read-Host 'Merge these into master and push to GitHub (public)? [y/N]'
            if ($answer -ne 'y') { exit 0 }
            git -C $Repo merge --no-edit agent
            Assert-Ok 'git merge agent'
        }
        git -C $Repo push origin master
        Assert-Ok 'git push'
    }
    'update' {
        git -C $Sandbox fetch --quiet origin
        Assert-Ok 'git fetch origin'
        git -C $Sandbox merge --no-edit origin/master
        Assert-Ok 'git merge origin/master'
    }
    'rebuild' {
        Initialize-Clone
        docker compose -f $ComposeFile build --pull
        Assert-Ok 'docker compose build'
        docker compose -f $ComposeFile up -d --force-recreate
        Assert-Ok 'docker compose up'
    }
    'down' {
        docker compose -f $ComposeFile down
    }
}
