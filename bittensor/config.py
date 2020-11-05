from configparser import ConfigParser
from substrateinterface import Keypair
from loguru import logger
import configparser
import argparse
import requests

import validators
import pathlib
from bittensor.crypto import Crypto


class InvalidConfigFile(Exception):
    pass


class ValidationError(Exception):
    pass


class PostProcessingError(Exception):
    pass


class InvalidConfigError(Exception):
    pass

class Config(dict):
    CHAIN_ENDPOINT = "chain_endpoint"
    AXON_PORT = "axon_port"
    METAGRAPH_PORT = "metagraph_port"
    METAGRAPH_SIZE = "metagraph_size"
    BOOTSTRAP = "bootstrap"
    KEYPAIR = "keypair"
    SUBSTRATE_URI = "substrate_uri"
    REMOTE_IP = "remote_ip"
    DATAPATH = "datapath"
    LOGDIR = "logdir"

    def __init__(self, *args, **kwargs):
        super().__init__()

        self.update(
            {
                Config.CHAIN_ENDPOINT: "http://127.0.0.1:9933",
                Config.DATAPATH: "data/",
                Config.SUBSTRATE_URI: "Alice",
                Config.LOGDIR: "data/",
                Config.REMOTE_IP: None,
                Config.AXON_PORT: 8091,
                Config.METAGRAPH_PORT: 8092,
                Config.METAGRAPH_SIZE: 10000,
                Config.BOOTSTRAP: None
            }
        )

        # Override (or not) options with default settings
        for key, value in kwargs.items():
            self[key] = value

    def log(self):
        for key in self:
            logger.info("CONFIG: %s: %s" % (key, self[key]))


    def get_bootpeer(self):
        if self[self.BOOTSTRAP]:
            return self[self.BOOTSTRAP]

        return None

    def __getattr__(self, item):
        if item in self:
            return self[item]
        


class ConfigService:
    # Attributes to make parsing of a config file work
    parser = None
    filename = None  # This will be passed as a constructor arg

    # The dict that hold the configuration
    config = Config()

    # Attribute that tells if the configuration is valid
    valid = False

    # Command line arguments, filled during init
    cl_args = None

    def create(self, filename, argparser: argparse.ArgumentParser):
        self.filename = "%s/%s" % (str(pathlib.Path(__file__).parent.absolute()), filename)
        self.argparse = argparser
        self.add_cl_args(argparser)

    # def create(self):

        """
        This is what happens:
        1) The system defaults for the configuration is set
        2) Then, config.ini is loaded and any value set there is used to overwrite the configuration
        3) Then, the command line is parsed for options and used in the configuratoin
        4) Ultimately some post processing is applied. Specifically, an IP address is obtained from an IP if not configured
        """
        try:
            # self.__setup_defaults()
            self.__load_config()
            self.__parse_cl_args()
            self.__validate_config()
            self.__do_post_processing()

            return self.config

        except InvalidConfigError:
            return None

    def add_cl_args(self, parser: argparse.ArgumentParser):
        parser.add_argument('--chain_endpoint', dest=Config.CHAIN_ENDPOINT, type=str, help="bittensor chain endpoint")
        parser.add_argument('--axon_port', dest=Config.AXON_PORT, type=int,
                            help="TCP port that will be used to receive axon connections")
        parser.add_argument('--metagraph_port', dest=Config.METAGRAPH_PORT, type=int,
                            help='TCP port that will be used to receive metagraph connections')
        parser.add_argument('--metagraph_size', dest=Config.METAGRAPH_SIZE, type=int, help='Metagraph cache size')
        parser.add_argument('--bootstrap', dest=Config.BOOTSTRAP, type=str,
                            help='The socket of the bootstrap peer host:port')
        parser.add_argument('--substrate_uri', dest=Config.SUBSTRATE_URI, type=str, help='Substrate URI e.g. ALICE')
        parser.add_argument('--remote_ip', dest=Config.REMOTE_IP, type=str,
                            help='The IP address of this neuron that will be published to the network')
        parser.add_argument('--datapath', dest=Config.DATAPATH, type=str, help='Path to datasets')
        parser.add_argument('--logdir', dest=Config.LOGDIR, type=str, help='Path to logs and saved models')

        self.cl_args = parser.parse_args()

    def __load_config(self):
        try:
            self.__parse_config_file()
        except FileNotFoundError:
            logger.debug("CONFIG: Warning: %s not found" % self.filename)
        except (InvalidConfigFile, ValueError):
            logger.error(
                "CONFIG: %s is invalid. Try copying and adapting the default configuration file." % self.filename)
            raise InvalidConfigError
        except Exception:
            logger.error("CONFIG: An unspecified error occured.")
            raise InvalidConfigError

    def __parse_config_file(self):
        """
        Loads and parses config.ini

        Throws:
            FileNotFoundError

        """
        self.parser = ConfigParser(allow_no_value=True)

        files_read = self.parser.read(self.filename)
        if self.filename not in files_read:
            raise FileNotFoundError

        # At this point, all sections and options are present. Now load the actual values according to type
        self.load_str(Config.CHAIN_ENDPOINT, "general", "chain_endpoint")
        self.load_str(Config.SUBSTRATE_URI, "general", "substrate_uri")
        self.load_str(Config.DATAPATH, "general", "datapath")
        self.load_str(Config.LOGDIR, "general", "logdir")

        self.load_str(Config.REMOTE_IP, "general", "remote_ip")
        self.load_int(Config.AXON_PORT, "axon", "port")

        self.load_int(Config.METAGRAPH_PORT, "metagraph", "port")
        self.load_int(Config.METAGRAPH_SIZE, "metagraph", "size")

        self.load_str(Config.BOOTSTRAP, "bootstrap", "socket")

    def __parse_cl_args(self):
        """

        This will loop over each command line argument. If it has a value,
        it is used to overwrite the already existing configuration

        Args:
            args: The output of the argparse parser's .parse_args() function

        Returns:

        """
        args_dict = vars(self.cl_args)
        for key in args_dict:
            if args_dict[key]:
                self.config[key] = args_dict[key]

    def __validate_config(self):
        # Now validate all settings

        # Todo: Implement chain endpoint validation
        try:
            # Chain endpoint is not implemented yet, no validation
            self.validate_substrate_uri(Config.SUBSTRATE_URI, required=True)

            self.validate_path(Config.DATAPATH, required=True)
            self.validate_path(Config.LOGDIR, required=True)
            self.validate_ip(Config.REMOTE_IP, required=False)

            self.validate_int_range(Config.AXON_PORT, min=1024, max=65535, required=True)

            self.validate_int_range(Config.METAGRAPH_PORT, min=1024, max=65535, required=True)
            self.validate_int_range(Config.METAGRAPH_SIZE, min=5, max=20000, required=True)

            self.validate_socket(Config.BOOTSTRAP, required=False)

        except ValidationError:
            logger.debug("CONFIG: Validation error")
            raise InvalidConfigError

    def __do_post_processing(self):
        try:
            self.__obtain_ip_address()
            self.__fix_paths()
        except PostProcessingError:
            logger.debug("CONFIG: post processing error.")
            raise InvalidConfigError

    def __obtain_ip_address(self):
        if self.config[Config.REMOTE_IP]:
            return
        try:
            value = requests.get('https://api.ipify.org').text
        except:
            logger.error("CONFIG: Could not retrieve public facing IP from IP API.")
            raise PostProcessingError

        if not validators.ipv4(value):
            logger.error("CONFIG: Response from IP API is not a valid IP.")
            raise PostProcessingError

        self.config[Config.REMOTE_IP] = value

    def __fix_paths(self):
        if self.config[Config.DATAPATH] and self.config[Config.DATAPATH][-1] != '/':
            self.config[Config.DATAPATH] += '/'

        if self.config[Config.LOGDIR] and self.config[Config.LOGDIR][-1] != '/':
            self.config[Config.LOGDIR] += '/'

    def load_config_option(self, section, option):
        """

        This function loads a config option from the config file.
        Note: Do not use this directly, instead use the wrapper functions
        * load_str
        * load_int

        As they cast the value to the right type

        Args:
            key:   Key of the config dict
            section:  section of the config file
            option:  the option of the config file

        Returns:
            * None when the config option does not exist
            * The string encoded value of the option (if there is not value, the string will be empty)

        Throws:
            InvalidConfigFile in case of a section not being present
        """
        try:
            return self.parser.get(section, option)
        except configparser.NoSectionError:
            logger.error("Section %s not found in config.ini" % section)
            raise InvalidConfigFile
        except configparser.NoOptionError:
            return None

    def load_str(self, key, section, option):
        """
        Loads values that should be parsed as string
        """
        value = self.load_config_option(section, option)
        if value is None:
            return

        self.config[key] = value

    def load_int(self, key, section, option):
        """
        Loads values that should be parsed as an int
        """
        try:
            # Return None if option has no value
            value = self.load_config_option(section, option)
            if value is None:
                return

            value = int(value)

            self.config[key] = value

        except ValueError:
            logger.error(
                "CONFIG: An error occured while parsing config.ini. Option '%s' in section '%s' should be an integer" % (
                option, section))
            raise ValueError

    '''
    Validation routines
    '''

    def has_valid_empty_value(self, config_key, required):
        value = self.config[config_key]
        if not value and required:
            logger.error("CONFIG: An error occured while parsing configuration. %s is required" % config_key)
            raise ValidationError
        if not value and not required:
            return True

        return False


    def validate_substrate_uri(self, config_key, required=False):
        """
        Validates the uri is in specific set \in [Alice, Bob]
        """
        
        value = self.config[config_key]

        if value not in ['Alice', 'Bob']:
            logger.error(
                "CONFIG: Validation error: %s for option %s is not a valid substrate uri." %
                (value, config_key))

            raise ValidationError


    def validate_int_range(self, config_key, min, max, required=False):

        """
        Validates if a specifed integer falls in the specified range
        """
        if self.has_valid_empty_value(config_key, required):
            return

        value = self.config[config_key]

        if not validators.between(value, min=min, max=max):
            logger.error(
                "CONFIG: Validation error: %s should be between %i and %i." % (
                    config_key, min, max))
            raise ValidationError

    def validate_path(self, config_key, required=False):
        if self.has_valid_empty_value(config_key, required):
            return

        path = self.config[config_key]

        try:
            pathlib.Path(path).mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.error("CONFIG: Validation error: no permission to create path %s for option %s" %
                         (path, config_key))
            raise ValidationError
        except:
            logger.error("CONFIG: Validation error: An undefined error occured while trying to create path %s for option %s" %
                         (path, config_key))
            raise ValidationError

    def validate_ip(self, config_key, required=False):
        if self.has_valid_empty_value(config_key, required):
            return

        value = self.config[config_key]

        if not validators.ipv4(value):
            logger.error(
                "CONFIG: Validation error: %s for option %s is not a valid ip address" %
                (value, config_key))

            raise ValidationError

    def validate_hostname(self, config_key, required=False):
        if self.has_valid_empty_value(config_key, required):
            return

        value = self.config[config_key]

        if not validators.ipv4(value) and not validators.domain(value):
            logger.error(
                "CONFIG: Validation error: %s for option %s is not a valid ip address or hostname" %
                (value, config_key))

            raise ValidationError

    def validate_socket(self, config_key, required=False):
        if self.has_valid_empty_value(config_key, required):
            return

        value = self.config[config_key]

        try:
            host, port =  value.split(":")
        except ValueError:
            logger.error(
                "CONFIG: Validation error: %s for option %s is incorrectly formatted. Should be ip:port" %
                (value, config_key))
            raise ValidationError

        if not validators.ipv4(host) and host != "localhost" and not validators.domain(host):
            logger.error(
                "CONFIG: Validation error: %s for option %s does not contain a valid ip address" %
                (value, config_key))

            raise ValidationError

        try:
            port = int(port)
        except ValueError:
            logger.error(
                "CONFIG: Validation error: %s for option %s does contain not a valid port nr" %
                (value, config_key))

            raise ValidationError

        if not validators.between(port, min=1024, max=65535):
            logger.error(
                "CONFIG: Validation error: %s for option %s port must be between 1024 and 65535" %
                (value, config_key))

            raise ValidationError

class SynapseConfig(object):
    r"""Base config for all synapse objects.
    Handles a parameters common to all bittensor synapse objects.

    Args:
         synapse_key (:obj:`str(ed25519 key)`, `optional`, defaults to :obj:`random str(ed25519)`):
            Cryptographic keys used by this synapse. Defaults to randomly generated ed25519 key.
    """
    __default_synapse_key__ = Crypto.public_key_to_string(
        Crypto.generate_private_ed25519().public_key())

    def __init__(self, **kwargs):
        # Bittensor synapse key.
        self.synapse_key = kwargs.pop("synapse_key", SynapseConfig.__default_synapse_key__)
        self._base_run_type_checks()

    def _base_run_type_checks(self):
        assert isinstance(self.synapse_key, type(SynapseConfig.__default_synapse_key__))

    def __str__(self):
        return "\n chain_endpoint: {} \n neuron key: {} \n axon port: {} \n metagraph port: {} \n metagraph Size: {} \n bootpeer: {} \n remote_ip: {} \n datapath: {} \n logdir: {}".format(
            self.chain_endpoint, self.neuron_key, self.axon_port, self.metagraph_port,
            self.metagraph_size, self.bootstrap, self.remote_ip, self.datapath, self.logdir)

    @staticmethod
    def from_hparams(hparams):
        config = Config()
        config.set_hparams(hparams)
        return config

    def set_hparams(self, hparams):
        for key, value in hparams.__dict__.items():
            try:
                setattr(self, key, value)
            except AttributeError as err:
                logger.error("Can't set {} with value {} for {}".format(
                    key, value, self))
                raise err
        self.run_type_checks()

    @staticmethod
    def add_args(parser: argparse.ArgumentParser):
        parser.add_argument('--chain_endpoint',
                            default=Config.__chainendpoint_default__,
                            type=str,
                            help="bittensor chain endpoint.")
        parser.add_argument('--axon_port',
                            default=Config.__axon_port_default__,
                            type=str,
                            help="Axon terminal bind port")
        parser.add_argument('--metagraph_port',
                            default=Config.__metagraph_port_default__,
                            type=str,
                            help='Metagraph bind port.')
        parser.add_argument('--metagraph_size',
                            default=Config.__metagraph_size_default__,
                            type=int,
                            help='Metagraph cache size.')
        parser.add_argument('--bootstrap',
                            default=Config.__bootstrap_default__,
                            type=str,
                            help='Metagraph bootpeer')
        parser.add_argument('--neuron_key',
                            default=Config.__neuron_key_default__,
                            type=str,
                            help='Neuron key')
        parser.add_argument('--remote_ip',
                            default=Config.__remote_ip_default__,
                            type=str,
                            help='Remote serving ip.')
        parser.add_argument('--datapath',
                            default=Config.__datapath_default__,
                            type=str,
                            help='Path to datasets.')
        parser.add_argument('--logdir',
                            default=Config.__logdir_default__,
                            type=str,
                            help='Path to logs and saved models.')
        return parser
