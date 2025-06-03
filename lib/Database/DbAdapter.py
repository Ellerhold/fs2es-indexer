#-*- coding: utf-8 -*-


class DbAdapter(object):
    """ An adapter for a database """

    def is_usable(self) -> bool:
        """
        Analyzes the database and reports back if it should be recreated

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """
        pass

    def prepare(self):
        """
        Prepares the database

        See https://gitlab.com/samba-team/samba/-/blob/master/source3/rpc_server/mdssvc/elasticsearch_mappings.json
        for the fields expected by samba and their mappings to the expected Spotlight results
        """
        pass

    def refresh_index(self):
        """ Refresh the elasticsearch index """
        pass
