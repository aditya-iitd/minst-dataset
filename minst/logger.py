import logging


class ParamFilter(logging.Filter):
    def __init__(self, param=None):
        self.param = param

    def filter(self, record):
        if self.param is None:
            allow = True
        else:
            allow = self.param not in record.msg

        return allow


LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,  # this fixes the problem

    'filters': {
        'soxfilter': {
            '()': ParamFilter,
            'param': 'sox'
        }
    },

    'formatters': {
        'standard': {
            'format': '%(asctime)s {%(filename)s:%(name)s} [%(levelname)s] '
                      '%(funcName)s(): %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'standard'
            # 'filters': ['soxfilter']
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': True
        }
    }
}


def get_config(level):
    theconfig = LOGGING_CONFIG.copy()
    theconfig['loggers']['']['level'] = level

    logging.getLogger('fileio.py').propagate = False
    logging.getLogger('claudio.sox').propagate = False
    return theconfig
