
"""Database tools."""

import os
from cStringIO import StringIO
from quoting import quote_copy, quote_literal

#
# Fully qualified table name
#

def fq_name_parts(tbl):
    "Return fully qualified name parts."

    tmp = tbl.split('.')
    if len(tmp) == 1:
        return ('public', tbl)
    elif len(tmp) == 2:
        return tmp
    else:
        raise Exception('Syntax error in table name:'+tbl)

def fq_name(tbl):
    "Return fully qualified name."
    return '.'.join(fq_name_parts(tbl))

#
# info about table
#
def get_table_oid(curs, table_name):
    schema, name = fq_name_parts(table_name)
    q = """select c.oid from pg_namespace n, pg_class c
           where c.relnamespace = n.oid
             and n.nspname = %s and c.relname = %s"""
    curs.execute(q, [schema, name])
    res = curs.fetchall()
    if len(res) == 0:
        raise Exception('Table not found: '+table_name)
    return res[0][0]

def get_table_pkeys(curs, tbl):
    oid = get_table_oid(curs, tbl)
    q = "SELECT k.attname FROM pg_index i, pg_attribute k"\
        " WHERE i.indrelid = %s AND k.attrelid = i.indexrelid"\
        "   AND i.indisprimary AND k.attnum > 0 AND NOT k.attisdropped"\
        " ORDER BY k.attnum"
    curs.execute(q, [oid])
    return map(lambda x: x[0], curs.fetchall())

def get_table_columns(curs, tbl):
    oid = get_table_oid(curs, tbl)
    q = "SELECT k.attname FROM pg_attribute k"\
        " WHERE k.attrelid = %s"\
        "   AND k.attnum > 0 AND NOT k.attisdropped"\
        " ORDER BY k.attnum"
    curs.execute(q, [oid])
    return map(lambda x: x[0], curs.fetchall())

#
# exist checks
#
def exists_schema(curs, schema):
    q = "select count(1) from pg_namespace where nspname = %s"
    curs.execute(q, [schema])
    res = curs.fetchone()
    return res[0]

def exists_table(curs, table_name):
    schema, name = fq_name_parts(table_name)
    q = """select count(1) from pg_namespace n, pg_class c
           where c.relnamespace = n.oid and c.relkind = 'r'
             and n.nspname = %s and c.relname = %s"""
    curs.execute(q, [schema, name])
    res = curs.fetchone()
    return res[0]

def exists_type(curs, type_name):
    schema, name = fq_name_parts(type_name)
    q = """select count(1) from pg_namespace n, pg_type t
           where t.typnamespace = n.oid
             and n.nspname = %s and t.typname = %s"""
    curs.execute(q, [schema, name])
    res = curs.fetchone()
    return res[0]

def exists_function(curs, function_name, nargs):
    # this does not check arg types, so may match several functions
    schema, name = fq_name_parts(function_name)
    q = """select count(1) from pg_namespace n, pg_proc p
           where p.pronamespace = n.oid and p.pronargs = %s
             and n.nspname = %s and p.proname = %s"""
    curs.execute(q, [nargs, schema, name])
    res = curs.fetchone()
    return res[0]

def exists_language(curs, lang_name):
    q = """select count(1) from pg_language
           where lanname = %s"""
    curs.execute(q, [lang_name])
    res = curs.fetchone()
    return res[0]

#
# Support for PostgreSQL snapshot
#

class Snapshot(object):
    "Represents a PostgreSQL snapshot."

    def __init__(self, str):
        "Create snapshot from string."

        self.sn_str = str
        tmp = str.split(':')
        if len(tmp) != 3:
            raise Exception('Unknown format for snapshot')
        self.xmin = int(tmp[0])
        self.xmax = int(tmp[1])
        self.txid_list = []
        if tmp[2] != "":
            for s in tmp[2].split(','):
                self.txid_list.append(int(s))

    def contains(self, txid):
        "Is txid visible in snapshot."

        txid = int(txid)

        if txid < self.xmin:
            return True
        if txid >= self.xmax:
            return False
        if txid in self.txid_list:
            return False
        return True

#
# Copy helpers
#

def _gen_dict_copy(tbl, row, fields):
    tmp = []
    for f in fields:
        v = row[f]
        tmp.append(quote_copy(v))
    return "\t".join(tmp)

def _gen_dict_insert(tbl, row, fields):
    tmp = []
    for f in fields:
        v = row[f]
        tmp.append(quote_literal(v))
    fmt = "insert into %s (%s) values (%s);"
    return fmt % (tbl, ",".join(fields), ",".join(tmp))

def _gen_list_copy(tbl, row, fields):
    tmp = []
    for i in range(len(fields)):
        v = row[i]
        tmp.append(quote_copy(v))
    return "\t".join(tmp)

def _gen_list_insert(tbl, row, fields):
    tmp = []
    for i in range(len(fields)):
        v = row[i]
        tmp.append(quote_literal(v))
    fmt = "insert into %s (%s) values (%s);"
    return fmt % (tbl, ",".join(fields), ",".join(tmp))

def magic_insert(curs, tablename, data, fields = None, use_insert = 0):
    """Copy/insert a list of dict/list data to database.
    
    If curs == None, then the copy or insert statements are returned
    as string.  For list of dict the field list is optional, as its
    possible to guess them from dict keys.
    """
    if len(data) == 0:
        return

    # decide how to process
    if type(data[0]) == type({}):
        if fields == None:
            fields = data[0].keys()
        if use_insert:
            row_func = _gen_dict_insert
        else:
            row_func = _gen_dict_copy
    else:
        if fields == None:
            raise Exception("Non-dict data needs field list")
        if use_insert:
            row_func = _gen_list_insert
        else:
            row_func = _gen_list_copy

    # init processing
    buf = StringIO()
    if curs == None and use_insert == 0:
        fmt = "COPY %s (%s) FROM STDIN;\n"
        buf.write(fmt % (tablename, ",".join(fields)))
 
    # process data
    for row in data:
        buf.write(row_func(tablename, row, fields))
        buf.write("\n")

    # if user needs only string, return it
    if curs == None:
        if use_insert == 0:
            buf.write("\\.\n")
        return buf.getvalue()

    # do the actual copy/inserts
    if use_insert:
        curs.execute(buf.getvalue())
    else:
        buf.seek(0)
        hdr = "%s (%s)" % (tablename, ",".join(fields))
        curs.copy_from(buf, hdr)

def db_copy_from_dict(curs, tablename, dict_list, fields = None):
    """Do a COPY FROM STDIN using list of dicts as source."""

    if len(dict_list) == 0:
        return

    if fields == None:
        fields = dict_list[0].keys()

    buf = StringIO()
    for dat in dict_list:
        row = []
        for k in fields:
            row.append(quote_copy(dat[k]))
        buf.write("\t".join(row))
        buf.write("\n")

    buf.seek(0)
    hdr = "%s (%s)" % (tablename, ",".join(fields))

    curs.copy_from(buf, hdr)

def db_copy_from_list(curs, tablename, row_list, fields):
    """Do a COPY FROM STDIN using list of lists as source."""

    if len(row_list) == 0:
        return

    if fields == None or len(fields) == 0:
        raise Exception('Need field list')

    buf = StringIO()
    for dat in row_list:
        row = []
        for i in range(len(fields)):
            row.append(quote_copy(dat[i]))
        buf.write("\t".join(row))
        buf.write("\n")

    buf.seek(0)
    hdr = "%s (%s)" % (tablename, ",".join(fields))

    curs.copy_from(buf, hdr)

#
# Full COPY of table from one db to another
#

class CopyPipe(object):
    "Splits one big COPY to chunks."

    def __init__(self, dstcurs, tablename, limit = 512*1024, cancel_func=None):
        self.tablename = tablename
        self.dstcurs = dstcurs
        self.buf = StringIO()
        self.limit = limit
        self.cancel_func = None
        self.total_rows = 0
        self.total_bytes = 0

    def write(self, data):
        "New data from psycopg"

        self.total_bytes += len(data)
        self.total_rows += data.count("\n")

        if self.buf.tell() >= self.limit:
            pos = data.find('\n')
            if pos >= 0:
                # split at newline
                p1 = data[:pos + 1]
                p2 = data[pos + 1:]
                self.buf.write(p1)
                self.flush()

                data = p2

        self.buf.write(data)

    def flush(self):
        "Send data out."

        if self.cancel_func:
            self.cancel_func()

        if self.buf.tell() > 0:
            self.buf.seek(0)
            self.dstcurs.copy_from(self.buf, self.tablename)
            self.buf.seek(0)
            self.buf.truncate()

def full_copy(tablename, src_curs, dst_curs, column_list = []):
    """COPY table from one db to another."""

    if column_list:
        hdr = "%s (%s)" % (tablename, ",".join(column_list))
    else:
        hdr = tablename
    buf = CopyPipe(dst_curs, hdr)
    src_curs.copy_to(buf, hdr)
    buf.flush()

    return (buf.total_bytes, buf.total_rows)


#
# SQL installer
#

class DBObject(object):
    """Base class for installable DB objects."""
    name = None
    sql = None
    sql_file = None
    def __init__(self, name, sql = None, sql_file = None):
        self.name = name
        self.sql = sql
        self.sql_file = sql_file
    def get_sql(self):
        if self.sql:
            return self.sql
        if self.sql_file:
            if self.sql_file[0] == "/":
                fn = self.sql_file
            else:
                contrib_list = [
                    "/opt/pgsql/share/contrib",
                    "/usr/share/postgresql/8.0/contrib",
                    "/usr/share/postgresql/8.0/contrib",
                    "/usr/share/postgresql/8.1/contrib",
                    "/usr/share/postgresql/8.2/contrib",
                ]
                for dir in contrib_list:
                    fn = os.path.join(dir, self.sql_file)
                    if os.path.isfile(fn):
                        return open(fn, "r").read()
                raise Exception('File not found: '+self.sql_file)
        raise Exception('object not defined')
    def create(self, curs):
        curs.execute(self.get_sql())

class DBSchema(DBObject):
    """Handles db schema."""
    def exists(self, curs):
        return exists_schema(curs, self.name)

class DBTable(DBObject):
    """Handles db table."""
    def exists(self, curs):
        return exists_table(curs, self.name)

class DBFunction(DBObject):
    """Handles db function."""
    def __init__(self, name, nargs, sql = None, sql_file = None):
        DBObject.__init__(self, name, sql, sql_file)
        self.nargs = nargs
    def exists(self, curs):
        return exists_function(curs, self.name, self.nargs)

class DBLanguage(DBObject):
    """Handles db language."""
    def __init__(self, name):
        DBObject.__init__(self, name, sql = "create language %s" % name)
    def exists(self, curs):
        return exists_language(curs, self.name)

def db_install(curs, list, log = None):
    """Installs list of objects into db."""
    for obj in list:
        if not obj.exists(curs):
            if log:
                log.info('Installing %s' % obj.name)
            obj.create(curs)
        else:
            if log:
                log.info('%s is installed' % obj.name)
