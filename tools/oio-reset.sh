#!/usr/bin/env bash

# oio-reset.sh
# Copyright (C) 2015-2017 OpenIO SAS, original work as part of OpenIO SDS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

set -e

NS=OPENIO
IP=
PORT=
OIO="$HOME/.oio"
SDS="$OIO/sds"
GRIDINIT_SOCK="${SDS}/run/gridinit.sock"
BOOTSTRAP_CONFIG=
SERVICE_ID=
RANDOM_SERVICE_ID=
PROFILE=
DATADIR="$SDS/data"

ZKSLOW=0
verbose=0
OPENSUSE=`grep -i opensuse /etc/*release || echo -n ''`

while getopts "D:P:I:N:f:Z:p:CRUv" opt; do
    case $opt in
        D) DATADIR="${OPTARG}" ;;
        P) PORT="${OPTARG}" ;;
        I) IP="${OPTARG}" ;;
        N) NS="${OPTARG}" ;;
        U) SERVICE_ID=1 ;;
        R) RANDOM_SERVICE_ID=1 ;;
        f) if [ -n "$OPTARG" ]; then
            if  [ ${OPTARG::1} != "/" ]; then
                BOOTSTRAP_CONFIG="${BOOTSTRAP_CONFIG} --conf ${PWD}/${OPTARG}"
            else
                BOOTSTRAP_CONFIG="${BOOTSTRAP_CONFIG} --conf ${OPTARG}"
            fi
        fi ;;
        Z) ZKSLOW=1 ;;
        p) PROFILE="${OPTARG}" ;;
        v) ((verbose=verbose+1)) ;;
        \?) exit 1 ;;
    esac
done

SERVICES="nb-services"
M1_STR="meta1"
M2_STR="meta2"
M2_REPLICAS="m2-replicas"

timeout () {
    num=$1 ; shift
    if [ $count -gt "$num" ] ; then
        echo "TIMEOUT! $*"
        oio-cluster -r "$NS"
        ( ps -o pid,ppid,cmd $(pgrep -u $UID -P "$pidof_gridinit" | sed 's/^/-p /') || exit 0 )
        exit 1
    fi
    sleep 1
    ((count=count+1))
}


#-------------------------------------------------------------------------------

cmd_openio="openio --oio-ns $NS"
G_DEBUG_LEVEL=WARN
if [ $verbose != 0 ] ; then
    G_DEBUG_LEVEL=TRACE
    echo "# $0" \
        "-I \"${IP}\"" \
        "-P \"${PORT}\"" \
        "-N \"${NS}\"" \
        "-Z \"${ZKSLOW}\"" \
        "${BOOTSTRAP_CONFIG}"
    cmd_openio="$cmd_openio -v --debug"
fi
export G_DEBUG_LEVEL

if [ $verbose -ge 1 ] ; then set -x ; fi

# Check the datadir is a directory the current user owns
[ -n "$DATADIR" ]
if [[ -e "$DATADIR" ]] ; then
    [ -d "$DATADIR" ]
    [ -O "$DATADIR" ]
    [ -r "$DATADIR" ]
    [ -x "$DATADIR" ]
    [ -w "$DATADIR" ]
fi

# Stop and clean a previous installation.
pgrep -u "$UID" --full gridinit | while read pidof_gridinit ; do
    # First try a clean stop of gridinit's children
    if [ -e "$GRIDINIT_SOCK" ] ; then
        if ! gridinit_cmd -S "$GRIDINIT_SOCK" stop >/dev/null ; then
            echo "Failed to send 'stop' to gridinit"
        fi
    fi
    # We know by experience this might fail, so try to kill gridinit's children
    if ! pkill -u "$UID" -P "$pidof_gridinit" ; then
        echo "Failed to kill gridinit children" 1>&2
    fi
    # Kill gridinit until it dies with its children
    count=0
    while kill "$pidof_gridinit" ; do
        # Waiting for gridinit ...
        if [ "$count" -gt 20 ] ; then
            echo "Gridinit doesn't want to die gracefully. Go for euthanasy"
            ( pkill -9 -u "$UID" oio-event-agent || exit 0 )
        fi
            timeout 30
        done
done

# Generate a new configuration and start the new gridinit

mkdir -p "$OIO"
cd "$OIO"
rm -rf sds.conf sds/{conf,run,logs}
if [[ -d "$DATADIR" ]] ; then
    rm -rf $DATADIR/${NS}*
fi

bootstrap_opt=
if [[ -n "${PORT}" ]] ; then bootstrap_opt="${bootstrap_opt} --port ${PORT}" ; fi
if [[ -n "${SERVICE_ID}" ]] ; then bootstrap_opt="${bootstrap_opt} --with-service-id" ; fi
if [[ -n "${RANDOM_SERVICE_ID}" ]] ; then bootstrap_opt="${bootstrap_opt} --random-service-id" ; fi
if [[ -n "${DATADIR}" ]] ; then bootstrap_opt="${bootstrap_opt} --data ${DATADIR}" ; fi
if [[ -n "${PROFILE}" ]] ; then bootstrap_opt="${bootstrap_opt} --profile ${PROFILE}" ; fi
oio-bootstrap.py $bootstrap_opt -d ${BOOTSTRAP_CONFIG} "$NS" "$IP" > /tmp/oio-bootstrap.$$


. /tmp/oio-bootstrap.$$
rm -f /tmp/oio-bootstrap.$$


gridinit -s OIO,gridinit -d ${SDS}/conf/gridinit.conf

# Initiate Zookeeper (if necessary)
ZK=$(oio-cluster --local-cfg | grep "$NS/zookeeper" ; exit 0)
if [ -n "$ZK" ] ; then
    #opts="--fuck-the-world"
    #if [ $verbose -ge 1 ] ; then opts="${opts} -v" ; fi
    #openio --oio-ns "$NS" zk armageddon ${opts}

    opts="--lazy"
    if [ $verbose -ge 1 ] ; then opts="${opts} -v" ; fi
    if [ $ZKSLOW -ne 0 ] ; then opts="${opts} --slow" ; fi
    openio --oio-ns "$NS" zk bootstrap ${opts}
fi


# Wait for the gridinit's startup
count=0
while ! pkill -u "$UID" --full -0 gridinit ; do
    timeout 15 "gridinit startup"
done
while ! [ -e "$GRIDINIT_SOCK" ] ; do
    timeout 30 "gridinit readyness"
done
pidof_gridinit=$(pgrep -u "$UID" --full gridinit)


echo -e "\n### Start gridinit and wait for the services to register"
gridinit_cmd -S "$GRIDINIT_SOCK" reload >/dev/null
gridinit_cmd -S "$GRIDINIT_SOCK" start "@${NS}" >/dev/null

COUNT=$(oio-test-config.py -c -t meta2 -t rawx -t sqlx -t meta0 -t meta1 -t rdir)
$cmd_openio cluster wait -d 30 -u -n "$COUNT" sqlx rawx meta2 meta0 meta1 rdir


echo -e "\n### Init the meta0/meta1 directory"
$cmd_openio directory bootstrap --check \
    --replicas $(oio-test-config.py -v directory_replicas)

# Help debugging "The current META0 service is not ready yet [...]"
if [ "$(oio-test-config.py -v directory_replicas)" -gt 1 ]
then
    $cmd_openio election status meta0 0000
fi

echo -e "\n### Assign rdir services"
# Force meta1 services to reload meta0 cache
for addr in $(oio-test-config.py -t meta1); do
    $cmd_openio cluster lock meta1 $addr
done
gridinit_cmd -S "$GRIDINIT_SOCK" restart "@meta1" >/dev/null
# Wait until the scores are at 0
MAX_WAITING="30"
COUNT_META1=$(oio-test-config.py -c -t meta1)
for i in $(seq 1 "$MAX_WAITING"); do
    COUNT_META1_0=$($cmd_openio cluster list meta1 -f value -c Score | grep -c "^0$" || true)
    if [ "$COUNT_META1_0" -eq "$COUNT_META1" ]; then
        break
    fi
    if [ "$i" -eq "$MAX_WAITING" ]; then
        exit 1
    fi
    sleep 1
done
$cmd_openio cluster wait -d 30 -u -n "$COUNT_META1" meta1

$cmd_openio rdir bootstrap rawx
$cmd_openio rdir bootstrap meta2

echo -e "\n### Wait for the services to have a score"
$cmd_openio cluster unlockall
oio-flush-all.sh -n "$NS" >/dev/null

echo -e "\n### Congrats, it's a NS"
find $SDS -type d | xargs chmod a+rx
gridinit_cmd -S "$GRIDINIT_SOCK" status2
oio-cluster -r "$NS"

echo -e "\nexport OIO_NS=$NS OIO_ACCT=ACCT-$RANDOM"
