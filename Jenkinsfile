def isMain() {
  def branch = env.BRANCH_NAME ?: env.GIT_BRANCH ?: ''
  return !env.CHANGE_ID && branch in ['main', 'origin/main', 'refs/heads/main']
}

pipeline {
  agent any

  environment {
    GITEA_URL = 'https://git.sejong.dev'
    GITEA_REPO = 'ysj7705/mudfish-decky'
    // The organization folder's Gitea token (Gitea plugin credentials also bind as a string).
    // It must be allowed to write this repository's releases.
    GITEA_CREDENTIALS_ID = 'gitea-ysj7705'
    PYTHON_IMAGE = 'python:3.14-slim'
    NODE_IMAGE = 'node:22-bookworm'
    PNPM = 'npx -y pnpm@9.15.9'
  }

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  stages {
    stage('Test') {
      steps {
        sh 'sh scripts/ci-run.sh "$PYTHON_IMAGE" sh -c "PYTHONPATH=py_modules python -m unittest discover -s tests -t . -v"'
      }
    }

    stage('Build') {
      steps {
        sh 'sh scripts/ci-run.sh "$NODE_IMAGE" sh -c "$PNPM install --frozen-lockfile && $PNPM build"'
      }
    }

    stage('Package') {
      steps {
        sh 'rm -rf out && sh scripts/ci-run.sh "$PYTHON_IMAGE" python scripts/package.py out'
        archiveArtifacts artifacts: 'out/*.zip', fingerprint: true
      }
    }

    stage('Release') {
      // A release is published once per package.json version: bump the version on main to ship.
      when { expression { isMain() } }
      steps {
        withCredentials([string(credentialsId: env.GITEA_CREDENTIALS_ID, variable: 'GITEA_TOKEN')]) {
          sh 'sh scripts/ci-run.sh "$PYTHON_IMAGE" python scripts/gitea_release.py out'
        }
      }
    }
  }
}
