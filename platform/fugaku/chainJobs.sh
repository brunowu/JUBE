#!/usr/bin/env bash

if [ $# -lt 2 ]
then
    echo "$0: ERROR (MISSING ARGUMENTS)"
    exit 1
fi

LOCKFILE=$1
shift
SUBMITSCRIPT=$*


if  [ -f $LOCKFILE ]
then
    DEPEND_JOBID=`head -1 $LOCKFILE`
    echo "pjsub --step --sparam jid=${DEPEND_JOBID} --no-check-directory $SUBMITSCRIPT"
    SUBMIT_OUTPUT=`pjsub --step --sparam jid=${DEPEND_JOBID} --no-check-directory $SUBMITSCRIPT`
    JOBID=$(echo "$SUBMIT_OUTPUT" | sed -n 's/.*Job \([0-9]*\)_\([0-9]\).*/\1/p')
else
    echo "pjsub --step --no-check-directory $SUBMITSCRIPT"
    SUBMIT_OUTPUT=`pjsub --step --no-check-directory $SUBMITSCRIPT`
    JOBID=$(echo "$SUBMIT_OUTPUT" | sed -n 's/.*Job \([0-9]*\)_\([0-9]\).*/\1/p')
fi

JUBE_ERR_CODE=$?
if [ $JUBE_ERR_CODE -ne 0 ]; then
    exit $JUBE_ERR_CODE
fi

echo "RETURN: $JOBID"
# the JOBID is the last field of the output line
echo ${JOBID##* } > $LOCKFILE

exit 0
