import sqlite3
from asynchelper import promise
from sqlite3 import OperationalError

class DB():
    def __init__(self):
        self.db = sqlite3.connect('clinvar.db', timeout=20, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.cursor = self.db.cursor()

    def and_equals(self, column, value):
        if type(value) == list:
            if not value:
                return
            db_types = {
                int: 'INTEGER',
                str: 'TEXT',
            }
            self.cursor.execute('DROP TABLE IF EXISTS ' + column) #the same connection may perform multiple queries
            self.cursor.execute('CREATE TEMP TABLE ' + column + ' (value ' + db_types[type(value[0])] + ')')
            self.cursor.execute('CREATE INDEX ' + column + '__value ON ' + column + ' (value)')
            self.cursor.executemany('INSERT INTO ' + column + ' VALUES (?)', map(lambda value: [value], value))
            self.query += ' AND ' + column + ' IN (SELECT value FROM ' + column + ')'
        else:
            self.query += ' AND ' + column + '=:' + column
            self.parameters[column] = value

    def rows(self):
        return list(map(dict, self.cursor.execute(self.query, self.parameters)))

    def value(self):
        return list(self.cursor.execute(self.query, self.parameters))[0][0]

    def condition_info(self, condition_name):
        try:
            #prefer a row that links the condition name to a condition ID
            row = list(self.cursor.execute('''
                SELECT condition_db, condition_id FROM current_submissions WHERE condition_name=?
                GROUP BY condition_id=='' ORDER BY condition_id=='' LIMIT 1
            ''', [condition_name]))[0]
            return {'db': row[0], 'id': row[1], 'name': condition_name}
        except IndexError:
            return None

    def country_name(self, country_code):
        try:
            return list(self.cursor.execute(
                'SELECT submitter_country_name FROM current_submissions WHERE submitter_country_code=? LIMIT 1',
                [country_code]
            ))[0][0]
        except IndexError:
            return None

    def gene_from_rsid(self, rsid):
        try:
            return list(self.cursor.execute(
                'SELECT DISTINCT gene FROM current_submissions WHERE variant_rsid=? LIMIT 1', [rsid]
            ))[0][0]
        except IndexError:
            return None

    def gene_info(self, gene):
        try:
            row = list(self.cursor.execute('SELECT gene_type FROM current_submissions WHERE gene=? LIMIT 1', [gene]))[0]
            ret = {'name': gene, 'type': row[0]}
        except IndexError:
            return None
        ret['see_also'] = list(map(
            lambda row: row[0],
            self.cursor.execute('SELECT see_also FROM gene_links WHERE gene=?', [gene])
        ))
        return ret

    def is_gene(self, gene):
        return bool(list(self.cursor.execute(
            'SELECT 1 FROM current_submissions WHERE gene=? LIMIT 1', [gene]
        )))

    def is_condition_name(self, condition_name):
        return bool(list(self.cursor.execute(
            'SELECT 1 FROM current_submissions WHERE condition_name=? LIMIT 1', [condition_name]
        )))

    def is_significance(self, significance):
        return bool(list(self.cursor.execute(
            'SELECT 1 FROM current_submissions WHERE significance=? LIMIT 1', [significance]
        )))

    def is_variant_name(self, variant_name):
        return bool(list(self.cursor.execute(
            'SELECT 1 FROM current_submissions WHERE variant_name=? LIMIT 1', [variant_name]
        )))

    def max_date(self):
        return list(self.cursor.execute('SELECT date FROM current_submissions LIMIT 1'))[0][0]

    def significance_term_info(self):
        return list(map(
            dict,
            self.cursor.execute('''
                SELECT significance, MIN(date) AS first_seen, MAX(date) AS last_seen FROM submissions
                GROUP BY significance ORDER BY last_seen DESC, first_seen DESC
            ''')
        ))

    def submissions(self, **kwargs):
        self.query = '''
            SELECT
                variant_name,
                submitter1_id AS submitter_id,
                submitter1_name AS submitter_name,
                rcv1 AS rcv,
                scv1 AS scv,
                significance1 AS significance,
                last_eval1 AS last_eval,
                review_status1 AS review_status,
                condition1_db AS condition_db,
                condition1_id AS condition_id,
                condition1_name AS condition_name,
                method1 AS method,
                comment1 AS comment
            FROM current_comparisons
            WHERE star_level1>=:min_stars AND star_level2>=:min_stars AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars': kwargs.get('min_stars', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('variant_name'):
            self.and_equals('variant_name', kwargs['variant_name'])

        if kwargs.get('normalized_method'):
            self.and_equals('normalized_method1', kwargs['normalized_method'])
            self.and_equals('normalized_method2', kwargs['normalized_method'])

        self.query += ' GROUP BY scv1 ORDER BY submitter_name'

        return self.rows()

    def submitter_id_from_name(self, submitter_name):
        try:
            return list(self.cursor.execute(
                'SELECT submitter_id FROM current_submissions WHERE submitter_name=? LIMIT 1', [submitter_name]
            ))[0][0]
        except IndexError:
            return None

    def submitter_info(self, submitter_id):
        try:
            row = list(self.cursor.execute('''
                SELECT submitter_id, submitter_name, submitter_country_name
                FROM current_submissions WHERE submitter_id=? LIMIT 1
                ''', [submitter_id]
            ))[0]
            return {'id': row[0], 'name': row[1], 'country_name': row[2]}
        except IndexError:
            return None

    def submitter_primary_method(self, submitter_id):
        return list(
            self.cursor.execute('''
                SELECT method FROM current_submissions WHERE submitter_id=?
                GROUP BY method ORDER BY COUNT(*) DESC LIMIT 1
            ''', [submitter_id])
        )[0][0]

    @promise
    def total_conflicting_variants_by_condition_and_conflict_level(self, **kwargs):
        self.query = '''
            SELECT condition1_name AS condition_name, conflict_level, COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', 1),
        }

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        self.query += ' GROUP BY condition_name, conflict_level'

        return list(map(dict, self.cursor.execute(self.query, self.parameters)))

    @promise
    def total_conflicting_variants_by_conflict_level(self, **kwargs):
        self.query = '''
            SELECT conflict_level, COUNT(DISTINCT variant_name) AS count FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', 1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('submitter2_id'):
            self.and_equals('submitter2_id', kwargs['submitter2_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        self.query += ' GROUP BY conflict_level'

        return self.rows()

    @promise
    def total_conflicting_variants_by_gene_and_conflict_level(self, **kwargs):
        self.query = '''
            SELECT gene, conflict_level, COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', 1),
        }

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type') != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        if kwargs.get('gene'):
            self.and_equals('gene', kwargs['gene'])

        self.query += ' GROUP BY gene, conflict_level'

        return list(map(dict, self.cursor.execute(self.query, self.parameters)))

    @promise
    def total_conflicting_variants_by_significance_and_significance(self, **kwargs):
        if kwargs.get('original_terms'):
            self.query = 'SELECT significance1, significance2'
        else:
            self.query = '''
                SELECT normalized_significance1 AS significance1, normalized_significance2 AS significance2
            '''

        self.query += ', conflict_level, COUNT(DISTINCT variant_name) AS count FROM current_comparisons'

        self.query += '''
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', 1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('submitter2_id'):
            self.and_equals('submitter2_id', kwargs['submitter2_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        if kwargs.get('original_terms'):
            self.query += ' GROUP BY significance1, significance2'
        else:
            self.query += ' GROUP BY normalized_significance1, normalized_significance2'

        return self.rows()

    @promise
    def total_conflicting_variants_by_submitter_and_conflict_level(self, **kwargs):
        if kwargs.get('submitter1_id'):
            self.query = 'SELECT submitter2_id AS submitter_id'
        else:
            self.query = 'SELECT submitter1_id AS submitter_id'

        self.query += '''
            , conflict_level, COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', 1),
        }

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('submitter_ids'):
            self.and_equals('submitter_id', kwargs['submitter_ids'])

        self.query += ' GROUP BY submitter_id, conflict_level'

        return self.rows()

    @promise
    def total_significance_terms_over_time(self):
        return list(map(
            dict,
            self.cursor.execute('SELECT date, COUNT(DISTINCT significance) AS count FROM submissions GROUP BY date')
        ))

    @promise
    def total_submissions(self):
        return list(self.cursor.execute('SELECT COUNT(*) FROM current_submissions'))[0][0]

    def total_submissions_by_country(self, **kwargs):
        self.query = '''
            SELECT
                submitter1_country_code AS country_code,
                submitter1_country_name AS country_name,
                COUNT(DISTINCT scv1) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars AND star_level2>=:min_stars AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars': kwargs.get('min_stars', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('normalized_method'):
            self.and_equals('normalized_method1', kwargs['normalized_method'])
            self.and_equals('normalized_method2', kwargs['normalized_method'])

        self.query += ' GROUP BY country_code ORDER BY count DESC'

        return self.rows()

    def total_submissions_by_method(self, **kwargs):
        return list(map(
            dict,
            self.cursor.execute(
                '''
                    SELECT method1 AS method, COUNT(DISTINCT scv1) AS count
                    FROM current_comparisons
                    WHERE star_level1>=:min_stars AND star_level2>=:min_stars AND conflict_level>=:min_conflict_level
                    GROUP BY method ORDER BY count DESC
                ''',
                {
                    'min_stars': kwargs.get('min_stars', 0),
                    'min_conflict_level': kwargs.get('min_conflict_level', -1),
                }
            )
        ))

    def total_submissions_by_normalized_method_over_time(self, **kwargs):
        return list(map(
            dict,
            self.cursor.execute(
                '''
                    SELECT date, normalized_method1 AS normalized_method, COUNT(DISTINCT scv1) AS count
                    FROM comparisons
                    WHERE star_level1>=:min_stars AND star_level2>=:min_stars AND conflict_level>=:min_conflict_level
                    GROUP BY date, normalized_method ORDER BY date, count DESC
                ''',
                {
                    'min_stars': kwargs.get('min_stars', 0),
                    'min_conflict_level': kwargs.get('min_conflict_level', -1),
                }
            )
        ))

    def total_submissions_by_submitter(self, **kwargs):
        self.query = '''
            SELECT submitter1_id AS submitter_id, submitter1_name AS submitter_name, COUNT(DISTINCT scv1) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars': kwargs.get('min_stars', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('country_code'):
            self.and_equals('submitter1_country_code', kwargs['country_code'])

        if kwargs.get('normalized_method'):
            self.and_equals('normalized_method1', kwargs['normalized_method'])

        self.query += ' GROUP BY submitter1_id ORDER BY count DESC'

        return self.rows()

    def total_variants(self, **kwargs):
        self.query = '''
            SELECT COUNT(DISTINCT variant_name) FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('submitter2_id'):
            self.and_equals('submitter2_id', kwargs['submitter2_id'])

        if kwargs.get('significance1'):
            if kwargs.get('original_terms'):
                self.and_equals('significance1', kwargs['significance1'])
            else:
                self.and_equals('normalized_significance1', kwargs['significance1'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        return self.value()

    @promise
    def total_variants_by_condition(self, **kwargs):
        self.query = '''
            SELECT
                condition1_db AS condition_db,
                condition1_id AS condition_id,
                condition1_name AS condition_name,
                COUNT(DISTINCT gene) AS gene_count,
                COUNT(DISTINCT submitter1_id) AS submitter_count,
                COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('significance1'):
            if kwargs.get('original_terms'):
                self.and_equals('significance1', kwargs['significance1'])
            else:
                self.and_equals('normalized_significance1', kwargs['significance1'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        self.query += ' GROUP BY condition_name ORDER BY count DESC'

        return list(map(dict, self.cursor.execute(self.query, self.parameters)))

    @promise
    def total_variants_by_condition_and_significance(self, **kwargs):
        self.query = 'SELECT condition1_name AS condition_name, COUNT(DISTINCT variant_name) AS count'

        if kwargs.get('original_terms'):
            self.query += ', significance1 AS significance'
        else:
            self.query += ', normalized_significance1 AS significance'

        self.query += '''
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        self.query += ' GROUP BY condition_name, significance'

        return self.rows()

    @promise
    def total_variants_by_gene(self, **kwargs):
        self.query = '''
            SELECT
                gene,
                COUNT(DISTINCT condition1_name) AS condition_count,
                COUNT(DISTINCT submitter1_id) AS submitter_count,
                COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('significance1'):
            if kwargs.get('original_terms'):
                self.and_equals('significance1', kwargs['significance1'])
            else:
                self.and_equals('normalized_significance1', kwargs['significance1'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        if kwargs.get('gene'):
            self.and_equals('gene', kwargs['gene'])

        self.query += ' GROUP BY gene ORDER BY count DESC'

        return self.rows()

    @promise
    def total_variants_by_gene_and_significance(self, **kwargs):
        self.query = 'SELECT gene, COUNT(DISTINCT variant_name) AS count'

        if kwargs.get('original_terms'):
            self.query += ', significance1 AS significance'
        else:
            self.query += ', normalized_significance1 AS significance'

        self.query += '''
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        self.query += ' GROUP BY gene, significance'

        return self.rows()

    @promise
    def total_variants_by_significance(self, **kwargs):
        self.query = 'SELECT COUNT(DISTINCT variant_name) AS count'

        if kwargs.get('original_terms'):
            self.query += ', significance1 AS significance'
        else:
            self.query += ', normalized_significance1 AS significance'

        self.query += '''
            , COUNT(DISTINCT gene) AS gene_count
            , COUNT(DISTINCT condition1_name) AS condition_count
            , COUNT(DISTINCT submitter1_id) AS submitter_count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        self.query += ' GROUP BY significance ORDER BY count DESC'

        return self.rows()

    @promise
    def total_variants_by_submitter(self, **kwargs):
        if kwargs.get('submitter1_id'):
            self.query = 'SELECT submitter2_id AS submitter_id, submitter2_name AS submitter_name'
        else:
            self.query = 'SELECT submitter1_id AS submitter_id, submitter1_name AS submitter_name'

        self.query += '''
            , COUNT(DISTINCT gene) AS gene_count
            , COUNT(DISTINCT condition1_name) AS condition_count
            , COUNT(DISTINCT variant_name) AS count
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('significance1'):
            if kwargs.get('original_terms'):
                self.and_equals('significance1', kwargs['significance1'])
            else:
                self.and_equals('normalized_significance1', kwargs['significance1'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        if kwargs.get('submitter_ids'):
            self.and_equals('submitter_id', kwargs['submitter_ids'])

        self.query += ' GROUP BY submitter_id ORDER BY count DESC'

        return self.rows()

    @promise
    def total_variants_by_submitter_and_significance(self, **kwargs):
        self.query = 'SELECT submitter1_id AS submitter_id, COUNT(DISTINCT variant_name) AS count'

        if kwargs.get('original_terms'):
            self.query += ', significance1 AS significance'
        else:
            self.query += ', normalized_significance1 AS significance'

        self.query += '''
            FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs['gene'])

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        self.query += ' GROUP BY submitter_id, significance'

        return self.rows()

    def variant_info(self, variant_name):
        try:
            row = list(self.cursor.execute(
                'SELECT variant_id, variant_rsid FROM current_submissions WHERE variant_name=? LIMIT 1', [variant_name]
            ))[0]
            return {'id': row[0], 'name': variant_name, 'rsid': row[1]}
        except IndexError:
            return None

    def variant_name_from_rcv(self, rcv):
        try:
            return list(self.cursor.execute(
                'SELECT variant_name FROM current_submissions WHERE rcv=? LIMIT 1', [rcv]
            ))[0][0]
        except IndexError:
            return None

    def variant_name_from_rsid(self, rsid):
        rows = list(self.cursor.execute(
            'SELECT DISTINCT variant_name FROM current_submissions WHERE variant_rsid=?', [rsid]
        ))
        return rows[0][0] if len(rows) == 1 else None

    def variant_name_from_scv(self, scv):
        try:
            return list(self.cursor.execute(
                'SELECT variant_name FROM current_submissions WHERE scv=? LIMIT 1', [scv]
            ))[0][0]
        except IndexError:
            return None

    @promise
    def variants(self, **kwargs):
        self.query = '''
            SELECT variant_name, variant_rsid FROM current_comparisons
            WHERE star_level1>=:min_stars1 AND star_level2>=:min_stars2 AND conflict_level>=:min_conflict_level
        '''

        self.parameters = {
            'min_stars1': kwargs.get('min_stars1', 0),
            'min_stars2': kwargs.get('min_stars2', 0),
            'min_conflict_level': kwargs.get('min_conflict_level', -1),
        }

        if kwargs.get('gene') != None:
            self.and_equals('gene', kwargs.get('gene'))

        if kwargs.get('condition1_name'):
            self.and_equals('condition1_name', kwargs['condition1_name'])

        if kwargs.get('submitter1_id'):
            self.and_equals('submitter1_id', kwargs['submitter1_id'])

        if kwargs.get('submitter2_id'):
            self.and_equals('submitter2_id', kwargs['submitter2_id'])

        if kwargs.get('significance1'):
            if kwargs.get('original_terms'):
                self.and_equals('significance1', kwargs['significance1'])
            else:
                self.and_equals('normalized_significance1', kwargs['significance1'])

        if kwargs.get('significance2'):
            if kwargs.get('original_terms'):
                self.and_equals('significance2', kwargs['significance2'])
            else:
                self.and_equals('normalized_significance2', kwargs['significance2'])

        if kwargs.get('normalized_method1'):
            self.and_equals('normalized_method1', kwargs['normalized_method1'])

        if kwargs.get('normalized_method2'):
            self.and_equals('normalized_method2', kwargs['normalized_method2'])

        if kwargs.get('gene_type', -1) != -1:
            self.query += ' AND gene_type=:gene_type'
            self.parameters['gene_type'] = kwargs['gene_type']

        self.query += ' GROUP BY variant_name ORDER BY variant_name'

        return self.rows()
