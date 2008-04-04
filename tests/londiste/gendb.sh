#! /bin/sh

. ../env.sh

contrib=/usr/share/postgresql/8.1/contrib
contrib=/opt/apps/pgsql-dev/share/contrib
contrib=/opt/pgsql/share/contrib



mkdir -p sys
./stop.sh
sleep 1

rm -rf file_logs sys
mkdir -p sys

db=db_root
echo "creating database: $db"
dropdb $db
sleep 1
createdb $db

londiste.py conf/w_root.ini init-root n_root "dbname=$db"

exit 0

pgqadm.py conf/ticker.ini install
psql -q $db -f data.sql

db=subscriber
echo "creating database: $db"
dropdb $db
sleep 1
createdb $db
pgqadm.py conf/linkticker.ini install
psql -q $db -f data.sql

db=file_subscriber
echo "creating database: $db"
dropdb $db
sleep 1
createdb $db
createlang plpgsql $db
createlang plpythonu $db
psql -q $db -f data.sql

echo "done, testing"

#pgqmgr.py -d conf/ticker.ini ticker
#./run-tests.sh

