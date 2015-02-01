#!/usr/bin/env python
# -*- coding: utf-8 -*-

__title__    = "ydcmd"
__version__  = "1.4"
__author__   = "Anton Batenev"
__license__  = "BSD"


__all__ = ["ydError", "ydCertError", "ydConfig", "ydOptions", "ydItem", "ydBase", "ydExtended", "ydCmd"]


import array, os, stat, pwd, grp, sys
import socket, ssl
import re, codecs, json
import time, datetime
import subprocess, tempfile
import hashlib, shutil


try:
    import dateutil.parser
    import dateutil.relativedelta

    # Hide UnicodeWarning in dateutil under Windows
    # https://bugs.launchpad.net/dateutil/+bug/1227221
    if os.name == "nt":
        import warnings
        warnings.filterwarnings("ignore", category = UnicodeWarning)

except ImportError:
    err = "Python module dateutil not found.\nPlease, install \"{0}\"\n"
    name = os.uname()[0]
    if name == "FreeBSD":
        sys.stderr.write(err.format("devel/py-dateutil"))
    elif name == "Linux":
        sys.stderr.write(err.format("python-dateutil"))
    sys.exit(1)


# PEP-8
try:
    import configparser
except ImportError:
    import ConfigParser as configparser


# PEP-469
try:
    dict.iteritems
except AttributeError:
    def itervalues(d):
        return iter(d.values())
    def iteritems(d):
        return iter(d.items())
    def listvalues(d):
        return list(d.values())
    def listitems(d):
        return list(d.items())
else:
    def itervalues(d):
        return d.itervalues()
    def iteritems(d):
        return d.iteritems()
    def listvalues(d):
        return d.values()
    def listitems(d):
        return d.items()


# PEP-3108
try:
    from http.client    import HTTPSConnection as ydHTTPSConnection
    from http.client    import NotConnected    as ydNotConnected
    from urllib.request import HTTPSHandler    as ydHTTPSHandler
    from urllib.request import Request         as ydRequest
    from urllib.request import build_opener    as yd_build_opener
    from urllib.error   import HTTPError       as ydHTTPError
    from urllib.error   import URLError        as ydURLError
    from urllib.parse   import urlencode       as yd_urlencode
except ImportError:
    from httplib        import HTTPSConnection as ydHTTPSConnection
    from httplib        import NotConnected    as ydNotConnected
    from urllib2        import HTTPSHandler    as ydHTTPSHandler
    from urllib2        import Request         as ydRequest
    from urllib2        import build_opener    as yd_build_opener
    from urllib2        import HTTPError       as ydHTTPError
    from urllib2        import URLError        as ydURLError
    from urllib         import urlencode       as yd_urlencode


class ydError(RuntimeError):
    """
    Внутреннее исключение, выбрасываемое в случаях:
        * Таймаут запроса к API
        * Исчерпание количества попыток запроса к API
        * Неверные аргументы, переданные в командной строке
    """
    def __init__(self, errno, errmsg):
        """
        Аргументы:
            errno  (int) -- Код ошибки (аналог кода возврата)
            errmsg (str) -- Текст ошибки
        """
        self.errno  = errno
        self.errmsg = "{0}".format(errmsg)


class ydCertError(ValueError):
    """
    Исключение при проверке валидности SSL сертификата
    """
    pass


class ydConfig(object):
    """
    Конфигурация приложения
    """
    @staticmethod
    def default_config():
        """
        Получение конфигурации приложения по умолчанию

        Результат (dict):
            Конфигурация приложения по умолчанию, которая может быть перегружена в вызове ydConfig.load_config
        """
        result = {
            "timeout"     : "30",
            "poll"        : "1",
            "retries"     : "3",
            "delay"       : "30",
            "limit"       : "100",   # default is 20
            "chunk"       : "512",   # default mdadm chunk size and optimal read-ahead is 512KB
            "token"       : "",
            "quiet"       : "no",
            "verbose"     : "no",
            "debug"       : "no",
            "async"       : "no",
            "rsync"       : "no",
            "attr"        : "no",
            "base-url"    : "https://cloud-api.yandex.net/v1/disk",
            "app-id"      : "2415aa2e6ceb4839b1202e15ac83536c",
            "app-secret"  : "b8ae32ce025c451f84bd7df17029cb55",
            "ca-file"     : "",
            "ciphers"     : "HIGH:!aNULL:!MD5:!3DES:!CAMELLIA:!SRP:!PSK:@STRENGTH",
            "depth"       : "1",
            "dry"         : "no",
            "type"        : "all",
            "keep"        : "",
            "encrypt"     : "no",
            "decrypt"     : "no",
            "encrypt-cmd" : "",
            "decrypt-cmd" : "",
            "temp-dir"    : ""
        }

        cafiles = [
            "/etc/ssl/certs/ca-certificates.crt",       # Debian, Ubuntu, Arch
            "/etc/pki/tls/certs/ca-bundle.trust.crt",   # CentOS, Fedora (EV certs)
            "/etc/ssl/ca-bundle.pem",                   # OpenSUSE
            "/usr/local/share/certs/ca-root-nss.crt"    # FreeBSD
        ]

        for cafile in cafiles:
            if os.path.isfile(cafile):
                result["ca-file"] = cafile
                break;

        return result


    @staticmethod
    def load_config(config = None, filename = os.path.expanduser("~") + "/.ydcmd.cfg"):
        """
        Чтение секции ydcmd INI файла ~/.ydcmd.cfg

        Аргументы:
            config   (dict) -- Базовая конфигурация
            filename (str)  -- Имя INI файла

        Результат (dict):
            Конфигурация приложения на основе файла конфигурации
        """
        if config == None:
            config = ydConfig.default_config()

        config = config.copy()

        parser = configparser.ConfigParser()
        parser.read(filename)

        for section in parser.sections():
            name = section.lower()
            if name == "ydcmd":
                for option in parser.options(section):
                    config[option.lower()] = parser.get(section, option).strip()

        return config


class ydOptions(object):
    """
    Опции приложения
    """
    def __init__(self, config = ydConfig.load_config()):
        """
        Аргументы:
            config (dict) -- конфигурация приложения
        """
        self.timeout   = int(config["timeout"])
        self.poll      = int(config["poll"])
        self.retries   = int(config["retries"])
        self.delay     = int(config["delay"])
        self.limit     = int(config["limit"])
        self.chunk     = int(config["chunk"]) * 1024
        self.token     = str(config["token"])
        self.quiet     = self._bool(config["quiet"])
        self.debug     = self._bool(config["debug"]) and not self.quiet
        self.verbose   = (self._bool(config["verbose"]) or self.debug) and not self.quiet
        self.async     = self._bool(config["async"])
        self.rsync     = self._bool(config["rsync"])
        self.attr      = self._bool(config["attr"])
        self.baseurl   = str(config["base-url"])
        self.appid     = str(config["app-id"])
        self.appsecret = str(config["app-secret"])
        self.cafile    = str(config["ca-file"])
        self.ciphers   = str(config["ciphers"])

        if self.ciphers == "":
            self.ciphers = None

        if self.cafile == "":
            self.cafile = None

        self.depth = int(config["depth"])
        self.dry   = self._bool(config["dry"])
        self.type  = str(config["type"])
        self.keep  = str(config["keep"])

        self.encrypt    = self._bool(config["encrypt"])
        self.decrypt    = self._bool(config["decrypt"])
        self.encryptcmd = str(config["encrypt-cmd"])
        self.decryptcmd = str(config["decrypt-cmd"])
        self.tempdir    = str(config["temp-dir"])

        if self.tempdir == "":
            self.tempdir = None

        self.short = True if "short" in config else None
        self.long  = True if "long"  in config else None
        self.human = True if "human" in config or (self.short == None and self.long == None) else None

        if "YDCMD_TOKEN" in os.environ:
            self.token = str(os.environ["YDCMD_TOKEN"])
        if "SSL_CERT_FILE" in os.environ:
            self.cafile = str(os.environ["SSL_CERT_FILE"])


    def __repr__(self):
        return "{0!s}({1!r})".format(self.__class__, self.__dict__)


    @staticmethod
    def _bool(value):
        """
        Преобразование строкового значения к булевому

        Аргументы:
            value (str|bool) -- Строковое представление булева значения

        Результат (bool):
            Результат преобразования строкового значения к булеву - [true|yes|t|y|1] => True, иначе False
        """
        if type(value) is bool:
            return value

        value = value.lower().strip()

        if value == "true" or value == "yes" or value == "t" or value == "y" or value == "1":
            return True

        return False


class ydItem(object):
    """
    Описатель элемента в хранилище
    """
    def __init__(self, info = None):
        """
        Аргументы:
            info (dict) -- Описатель элемента
        """
        common_attr = ["name", "created", "modified", "path", "type"]
        file_attr   = ["mime_type", "md5"]

        for attr in common_attr:
            if attr not in info:
                raise ValueError("{0} not exists (incomplete response?)".format(attr))

        if info != None:
            for key, value in iteritems(info):
                self.__dict__[key] = value

        if self.type == "file":
            for attr in file_attr:
                if attr not in info:
                    raise ValueError("{0} not exists (incomplete response?)".format(attr))
            if "size" not in info:
                self.__dict__["size"] = 0
        elif self.type == "dir":
            pass
        else:
            raise ValueError("Unknown item type: {0}".format(self.type))


    def isdir(self):
        return self.type == "dir"


    def isfile(self):
        return self.type == "file"


    def __str__(self):
        result = ""
        for key, value in iteritems(self.__dict__):
            result += "{0:>12}: {1}\n".format(key if key != "custom_properties" else "custom", value)
        return result


    def __repr__(self):
        return "{0!s}({1!r})".format(self.__class__, self.__dict__)


class ydBase(object):
    """
    Базовые методы работы с API
    """
    class _ydBaseHTTPSConnection(ydHTTPSConnection):
        """
        Сабклассинг ydHTTPSConnection для:
            * Проверки валидности SSL сертификата
            * Установки предпочитаемого набора шифров / алгоритма шифрования
            * Задания размера отсылаемого блока
        """
        def __init__(self, host, **kwargs):
            """
            Дополнительные аргументы:
                options (ydOptions) -- Опции приложения
            """
            self._options = kwargs.pop("options", None)
            ydHTTPSConnection.__init__(self, host, **kwargs)


        def _check_cert(self, cert, hostname):
            """
            Проверка валидности SSL сертификата

            Аргументы:
                cert     (dict) -- Данные сертификата
                hostname (str)  -- Имя хоста

            Исключения:
                ydCertError в случае ошибки проверки валидности сертификата
                (подробнее см. https://gist.github.com/zed/1347055)
            """
            def _dns(dn):
                pats = []
                for frag in dn.split(r"."):
                    if frag == '*':
                        pats.append("[^.]+")
                    else:
                        frag = re.escape(frag)
                        pats.append(frag.replace(r"\*", "[^.]*"))
                return re.compile(r"\A" + r"\.".join(pats) + r"\Z", re.IGNORECASE)


            if not cert:
                raise ValueError("Empty or no certificate")

            notafter = cert.get("notAfter", None)
            if notafter == None:
                raise ydCertError("No appropriate notAfter field were found in certificate")

            try:
                expire = dateutil.parser.parse(notafter).astimezone(dateutil.tz.tzutc())
            except:
                raise ydCertError("Can not parse cirtificate notAfter field")

            if expire < datetime.datetime.now(dateutil.tz.tzutc()).replace(microsecond = 0):
                raise ydCertError("Cirtificate expired at {0}".format(notafter))

            san      = cert.get("subjectAltName", ())
            dnsnames = []

            for key, value in san:
                if key == "DNS":
                    if _dns(value).match(hostname):
                        return
                    dnsnames.append(value)

            if not dnsnames:
                for sub in cert.get("subject", ()):
                    for key, value in sub:
                        if key == "commonName":
                            if _dns(value).match(hostname):
                                return
                            dnsnames.append(value)

            if len(dnsnames) > 1:
                raise ydCertError("Certificate hostname {0!r} doesn't match either of {1!s}".format(hostname, ", ".join(map(repr, dnsnames))))
            elif len(dnsnames) == 1:
                raise ydCertError("Certificate hostname {0!r} doesn't match {1!r}".format(hostname, dnsnames[0]))
            else:
                raise ydCertError("No appropriate commonName or subjectAltName fields were found in certificate")


        def connect(self):
            """
            Перегрузка ydHTTPSConnection.connect для проверки валидности SSL сертификата
            и установки предпочитаемого набора шифров / алгоритма шифрования
            """
            sock = socket.create_connection((self.host, self.port), self.timeout)

            if getattr(self, "_tunnel_host", None):
                self.sock = sock
                self._tunnel()

            kwargs = {}
            if self._options.cafile != None:
                kwargs.update (
                    cert_reqs = ssl.CERT_REQUIRED,
                    ca_certs  = self._options.cafile
                )

            if self._options.ciphers != None and ydBase.check_python23(7, 0, 2, 0):   # Python >= 2.7 / 3.2
                kwargs.update(ciphers = self._options.ciphers)

            sslv3_workaround = ydBase.check_python23(7, 9, 2, 0)   # Python >= 2.7.9 / 3.2
            if sslv3_workaround:
                kwargs.update(ssl_version = ssl.PROTOCOL_SSLv23)
            else:
                kwargs.update(ssl_version = ssl.PROTOCOL_TLSv1)

            self.sock = ssl.wrap_socket(sock, keyfile = self.key_file, certfile = self.cert_file, **kwargs)

            if sslv3_workaround:
                self.sock.context.options |= ssl.OP_NO_SSLv2
                self.sock.context.options |= ssl.OP_NO_SSLv3

            if self._options.debug:
                ciphers = self.sock.cipher()
                ydBase.debug("Connected to {0}:{1} ({2} {3})".format(self.host, self.port, self.sock.version() if ydBase.check_python23(7, 9, 5, 0) else ciphers[1], ciphers[0]))

            if self._options.cafile != None:
                try:
                    self._check_cert(self.sock.getpeercert(), self.host)
                except ydCertError:
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    raise


        def send(self, data):
            """
            Перегрузка ydHTTPConnection.send для возможности задания размера отсылаемого блока
            """
            if self.sock is None:
                if self.auto_open:
                    self.connect()
                else:
                    raise ydNotConnected()

            if hasattr(data, "read") and not isinstance(data, array.array):
                datablock = data.read(self._options.chunk)
                while datablock:
                    self.sock.sendall(datablock)
                    datablock = data.read(self._options.chunk)
            else:
                self.sock.sendall(data)


    class _ydBaseHTTPSHandler(ydHTTPSHandler):
        """
        Сабклассинг ydHTTPSHandler для:
            * Проверки валидности SSL сертификата
            * Установки предпочитаемого набора шифров / алгоритма шифрования
            * Задания размера отсылаемого блока
        """
        def __init__(self, options, debuglevel = 0):
            """
            Аргументы:
                options (ydOptions) -- Опции приложения
            """
            self._options = options

            ydHTTPSHandler.__init__(self, debuglevel)


        def https_open(self, req):
            """
            Перегрузка ydHTTPSHandler.https_open для использования _ydBaseHTTPSConnection
            """
            return self.do_open(self._get_connection, req)


        def _get_connection(self, host, **kwargs):
            """
            Callback создания _ydBaseHTTPSConnection
            """
            d = { "options" : self._options }
            d.update(kwargs)

            return ydBase._ydBaseHTTPSConnection(host, **d)


    def __init__(self, options):
        """
        Аргументы:
            options (ydOptions) -- конфигурация приложения
        """
        self.options = options


    @staticmethod
    def echo(msg):
        """
        Вывод сообщения

        Аргументы:
            msg (str) -- Сообщение для вывода в stdout
        """
        sys.stdout.write("{0}\n".format(msg))


    @staticmethod
    def verbose(errmsg, flag = True):
        """
        Вывод расширенной информации

        Аргументы:
            errmsg (str)  -- Сообщение для вывода в stderr
            flag   (bool) -- Флаг, разрешающий вывод сообщения
        """
        if flag:
            sys.stderr.write("{0}\n".format(errmsg))


    @staticmethod
    def debug(errmsg, flag = True):
        """
        Вывод отладочной информации

        Аргументы:
            errmsg (str)  -- Сообщение для вывода в stderr
            flag   (bool) -- Флаг, разрешающий вывод сообщения
        """
        if flag:
            sys.stderr.write("--> {0}\n".format(errmsg))


    @staticmethod
    def check_python23(py2minor, py2micro, py3minor, py3micro):
        """
        Проверка версии Python для обеспечения совместимости

        Аргументы:
            py2minor (int) -- minor версия для 2.x
            py2micro (int) -- micro версия для 2.x
            py3minor (int) -- minor версия для 3.x
            py3micro (int) -- micro версия для 3.x

        Результат (bool):
            Соответствие версии >= аргументам
        """
        return sys.version_info >= (2, py2minor, py2micro) if sys.version_info < (3, 0) else sys.version_info >= (3, py3minor, py3micro)


    def _headers(self):
        """
        Получение HTTP заголовков по умолчанию

        Результат (dict):
            Заголовки по умолчанию для передачи в запросе к API
        """
        return {
            "Accept"        : "application/json",
            "User-Agent"    : "ydcmd/{0} ({1})".format(__version__, "https://github.com/abbat/ydcmd"),
            "Authorization" : "OAuth {0}".format(self.options.token)
        }


    def query_retry(self, method, url, args, headers = None, filename = None, data = None):
        """
        Реализация одной попытки запроса к API

        Аргументы:
            method   (str)  -- Тип запроса (GET|POST|PUT|DELETE)
            url      (str)  -- URL запроса
            args     (dict) -- Параметры запроса
            headers  (dict) -- Заголовки запроса
            filename (str)  -- Имя файла для отправки / получения
            data     (str)  -- Данные для тела POST запроса

        Результат (dict):
            Результат вызова API, преобразованный из JSON

        Исключения:
            ydError     -- При возврате HTTP кода отличного от HTTP-200 (errno будет равен HTTP коду)
            ydCertError -- При ошибке проверки сертификата сервера
        """
        if headers == None:
            headers = self._headers()

        url += ("" if args == None else "?{0}".format(yd_urlencode(args)))

        if self.options.debug:
            self.debug("{0} {1}".format(method, url))
            if filename != None:
                self.debug("File: {0}".format(filename))

        # страховка
        if re.match('^https:\/\/[a-z0-9\.\-]+\.yandex\.(net|ru|com)(:443){,1}\/', url, re.IGNORECASE) == None:
            raise RuntimeError("Malformed URL {0}".format(url))

        if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            raise ValueError("Unknown method: {0}".format(method))

        fd = None
        if method == "PUT" and filename != None:
            fd = open(filename, "rb")
        elif (method == "POST" or method == "PATCH") and data != None:
            fd = data

        request = ydRequest(url, fd, headers)
        request.get_method = lambda: method

        try:
            opener = yd_build_opener(ydBase._ydBaseHTTPSHandler(self.options))
            result = opener.open(request, timeout = self.options.timeout)
            code   = result.getcode()

            if code == 204 or code == 201:
                return {}
            elif method == "GET" and filename != None:
                with open(filename, "wb") as fd:
                    while True:
                        part = result.read(self.options.chunk)
                        if not part:
                            break
                        fd.write(part)
                return {}
            else:
                def _json_convert(input):
                    """
                    Конвертер unicode строк в utf-8 при вызове json.load
                    """
                    if isinstance(input, dict):
                        return dict([(_json_convert(key), _json_convert(value)) for key, value in iteritems(input)])
                    elif isinstance(input, list):
                        return [_json_convert(element) for element in input]
                    elif isinstance(input, unicode):
                        return input.encode("utf-8")
                    else:
                        return input

                if sys.version_info < (3, 0):
                    return json.load(result, object_hook = _json_convert)
                else:
                    return json.load(codecs.getreader("utf-8")(result))

        except ydHTTPError as e:
            try:
                result = json.load(e)

                if "description" in result:
                    errmsg = "HTTP-{0}: {1}".format(e.code, result["description"])
                else:
                    errmsg = "HTTP-{0}: {1}".format(e.code, e.msg)
            except:
                errmsg = "HTTP-{0}: {1}".format(e.code, e.msg)

            raise ydError(e.code, errmsg)


    def query(self, method, url, args, headers = None, filename = None, data = None):
        """
        Реализация нескольких попыток запроса к API
        """
        retry = 0
        while True:
            try:
                return self.query_retry(method, url, args, headers, filename, data)
            except (ydURLError, ssl.SSLError) as e:
                retry += 1
                self.debug("Retry {0}/{1}: {2}".format(retry, self.options.retries, e), self.options.debug)
                if retry >= self.options.retries:
                    raise ydError(1, e)
                time.sleep(self.options.delay)


    def _wait(self, link):
        """
        Ожидание завершения операции

        Аргументы:
            link (dict) -- Ответ API на запрос операции
        """
        if self.options.async or not ("href" in link and "method" in link):
            return

        url    = link["href"]
        method = link["method"]

        while True:
            time.sleep(self.options.poll)

            result = self.query(method, url, None)

            if "status" in result:
                status = result["status"]
                if status == "in-progress":
                    continue
                elif status == "success":
                    break
                else:
                    raise RuntimeError("Unknown status: {0}".format(status))


    def info(self):
        """
        Получение метаинформации о хранилище

        Результат (dict):
            Метаинформация о хранилище
        """
        method = "GET"
        url    = self.options.baseurl + "/"

        return self.query(method, url, None)


    def stat(self, path):
        """
        Получение метаинформации об объекте в хранилище

        Аргументы:
            path (str) -- Имя файла или директории в хранилище

        Результат (ydItem):
            Метаинформация об объекте в хранилище
        """
        args = {
            "path"   : path,
            "offset" : 0,
            "limit"  : 0
        }

        method = "GET"
        url    = self.options.baseurl + "/resources"

        part = self.query(method, url, args)

        if "_embedded" in part:
            del part["_embedded"]

        return ydItem(part)


    def patch(self, path, info):
        """
        Добавление метаинформации объекту в хранилище

        Аргументы:
            path (str)  -- Имя файла или директории в хранилище
            info (dict) -- Метаинформация (без custom_properties)
        """
        self.verbose("Patch: {0}".format(path), self.options.verbose)

        args = {
            "path" : path
        }

        method  = "PATCH"
        url     = self.options.baseurl + "/resources"
        data    = "{\"custom_properties\": " + json.dumps(info, ensure_ascii = False) + "}"
        headers = self._headers()

        headers["Content-Length"] = len(data)
        headers["Content-Type"]   = "application/json"

        self.query(method, url, args, headers, None, data)


    def list(self, path):
        """
        Получение списка файлов и директорий в хранилище

        Аргументы:
            path (str) -- Объект хранилища

        Результат (dict):
            Список имен объектов и метаинформации о них { "имя" : ydItem }
        """
        result = {}

        args = {
            "path"   : path,
            "offset" : 0,
            "limit"  : self.options.limit
        }

        method = "GET"
        url    = self.options.baseurl + "/resources"

        while True:
            part = self.query(method, url, args)

            if "_embedded" in part:
                part = part["_embedded"]
            else:
                item = ydItem(part)
                result[item.name] = item
                return result

            for item in part["items"]:
                item = ydItem(item)
                result[item.name] = item

            if len(part["items"]) == int(part["limit"]):
                args["offset"] += int(part["limit"])
            else:
                break

        return result


    def last(self, limit):
        """
        Получение списка последних загруженных файлов

        Аргументы:
            limit (int) -- Количество файлов в списке

        Результат (dict):
            Список имен объектов и метаинформации о них { "путь" : ydItem }
        """
        result = {}

        args = None

        if limit > 0:
            args = {
                "limit" : limit
            }

        method = "GET"
        url    = self.options.baseurl + "/resources/last-uploaded"

        part = self.query(method, url, args)

        for item in part["items"]:
            item = ydItem(item)
            result[item.path] = item

        return result


    def delete(self, path):
        """
        Удаление объекта в хранилище

        Аргументы:
            path (str) -- Объект хранилища
        """
        self.verbose("Delete: {0}".format(path), self.options.verbose)

        args = {
            "path"        : path,
            "permanently" : "true"
        }

        method = "DELETE"
        url    = self.options.baseurl + "/resources"

        link = self.query(method, url, args)

        self._wait(link)


    def copy(self, source, target):
        """
        Копирование объекта в хранилище

        Аргументы:
            source (str) -- Исходный объект хранилища
            target (str) -- Конечный объект хранилища
        """
        self.verbose("Copy: {0} -> {1}".format(source, target), self.options.verbose)

        args = {
            "from"      : source,
            "path"      : target,
            "overwrite" : "true"
        }

        method = "POST"
        url    = self.options.baseurl + "/resources/copy"

        link = self.query(method, url, args)

        self._wait(link)


    def move(self, source, target):
        """
        Перемещение объекта в хранилище

        Аргументы:
            source (str) -- Исходный объект хранилища
            target (str) -- Конечный объект хранилища
        """
        self.verbose("Move: {0} -> {1}".format(source, target), self.options.verbose)

        args = {
            "from"      : source,
            "path"      : target,
            "overwrite" : "true"
        }

        method = "POST"
        url    = self.options.baseurl + "/resources/move"

        link = self.query(method, url, args)

        self._wait(link)


    def create(self, path):
        """
        Cоздание директории в хранилище

        Аргументы:
            path (str) -- Имя директории в хранилище
        """
        self.verbose("Create: {0}".format(path), self.options.verbose)

        args = {
            "path" : path
        }

        method = "PUT"
        url    = self.options.baseurl + "/resources"

        self.query(method, url, args)


    def publish(self, path):
        """
        Публикация объекта (объект становится доступен по прямой ссылке)

        Аргументы:
            path (str) -- Имя файла или директории в хранилище

        Результат (ydItem):
            Метаинформация об объекте в хранилище
        """
        self.verbose("Publish: {0}".format(path), self.options.verbose)

        args = {
            "path" : path
        }

        method = "PUT"
        url    = self.options.baseurl + "/resources/publish"

        self.query(method, url, args)

        return self.stat(path)


    def unpublish(self, path):
        """
        Закрытие публичного доступа к объекту (объект становится недоступен по прямой ссылке)

        Аргументы:
            path (str) -- Имя файла или директории в хранилище
        """
        self.verbose("Unpublish: {0}".format(path), self.options.verbose)

        args = {
            "path" : path
        }

        method = "PUT"
        url    = self.options.baseurl + "/resources/unpublish"

        self.query(method, url, args)


    def _put_retry(self, source, target):
        """
        Реализация одной попытки помещения файла в хранилище

        Аргументы:
            source (str) -- Имя локального файла
            target (str) -- Имя файла в хранилище
        """
        args = {
            "path"      : target,
            "overwrite" : "true"
        }

        method = "GET"
        url    = self.options.baseurl + "/resources/upload"

        result = self.query_retry(method, url, args)

        if "href" in result and "method" in result:
            url    = result["href"]
            method = result["method"]

            headers = self._headers()
            headers["Content-Type"]   = "application/octet-stream"
            headers["Content-Length"] = os.path.getsize(source)

            self.query_retry(method, url, None, headers, source)
        else:
            raise RuntimeError("Incomplete response")


    def put(self, source, target):
        """
        Реализация нескольких попыток загрузки файла в хранилище
        """
        if self.options.encrypt:
            if self.options.encryptcmd == "":
                raise ydError(1, "Encrypt error: --encrypt-cmd not defined but --encrypt used")
            try:
                dst = tempfile.NamedTemporaryFile(dir = self.options.tempdir, prefix = "ydcmd-", suffix = ".tmp")
                self.verbose("Encrypt: {0} -> {1}".format(source, dst.name), self.options.verbose)
                src = open(source, "rb")
                subprocess.check_call(self.options.encryptcmd, stdin = src, stdout = dst, shell = True)
                source = dst.name
            except Exception as e:
                raise ydError(1, "Encrypt error: {0}".format(e))

        self.verbose("Transfer: {0} -> {1}".format(source, target), self.options.verbose)

        retry = 0
        while True:
            try:
                self._put_retry(source, target)
                break
            except (ydURLError, ssl.SSLError) as e:
                retry += 1
                self.debug("Retry {0}/{1}: {2}".format(retry, self.options.retries, e), self.options.debug)
                if retry >= self.options.retries:
                    raise ydError(1, e)
                time.sleep(self.options.delay)


    def _get_retry(self, source, target):
        """
        Реализация одной попытки получения файла из хранилища

        Аргументы:
            source (str) -- Имя файла в хранилище
            target (str) -- Имя локального файла
        """
        args = {
            "path" : source
        }

        method = "GET"
        url    = self.options.baseurl + "/resources/download"

        result = self.query_retry(method, url, args)

        if "href" in result and "method" in result:
            url    = result["href"]
            method = result["method"]

            headers = self._headers()
            headers["Accept"] = "*/*"

            result = self.query_retry(method, url, None, headers, target)
        else:
            raise RuntimeError("Incomplete response")


    def get(self, source, target):
        """
        Реализация нескольких попыток получения файла из хранилища
        """
        if self.options.decrypt:
            if self.options.decryptcmd == "":
                raise ydError(1, "Decrypt error: --decrypt-cmd not defined but --decrypt used")
            try:
                src    = tempfile.NamedTemporaryFile(dir = self.options.tempdir, prefix = "ydcmd-", suffix = ".tmp")
                dst    = target
                target = src.name
            except Exception as e:
                raise ydError(1, "Decrypt error: {0}".format(e))

        self.verbose("Transfer: {0} -> {1}".format(source, target), self.options.verbose)

        retry = 0
        while True:
            try:
                self._get_retry(source, target)
                break
            except (ydURLError, ssl.SSLError) as e:
                retry += 1
                self.debug("Retry {0}/{1}: {2}".format(retry, self.options.retries, e), self.options.debug)
                if retry >= self.options.retries:
                    raise ydError(1, e)
                time.sleep(self.options.delay)

        if self.options.decrypt:
            try:
                target = dst
                self.verbose("Decrypt: {0} -> {1}".format(src.name, target), self.options.verbose)
                dst = open(target, "wb")
                subprocess.check_call(self.options.decryptcmd, stdin = src, stdout = dst, shell = True)
            except Exception as e:
                raise ydError(1, "Decrypt error: {0}".format(e))


class ydExtended(ydBase):
    """
    Расширенные методы api
    """
    def __init__(self, options):
        """
        Аргументы:
            options (ydOptions) -- Опции приложения
        """
        ydBase.__init__(self, options)


    def md5(self, filename):
        """
        Подсчет md5 хэша файла

        Аргументы:
            filename (str) -- Имя файла

        Результат (str):
            MD5 хэш файла
        """
        self.debug("MD5: " + filename, self.options.debug)

        with open(filename, "rb") as fd:
            hasher = hashlib.md5()
            while True:
                data = fd.read(self.options.chunk)
                if not data:
                    break
                hasher.update(data)

            return hasher.hexdigest()


    def _meta(self, path):
        """
        Получение метаинформации о локальном файле или директории

        Аргументы:
            path (str) -- Имя файла или директории

        Результат (dict):
            Метаинформация для отправки
        """
        info = os.stat(path)
        meta = {
            "ctime" : int(info.st_ctime),
            "mtime" : int(info.st_mtime),
            "uid"   : info.st_uid,
            "gid"   : info.st_gid,
            "mode"  : oct(stat.S_IMODE(info.st_mode)),
            "user"  : pwd.getpwuid(info.st_uid).pw_name,
            "group" : grp.getgrgid(info.st_gid).gr_name
        }

        return meta


    def _meta_diff(self, meta, stat):
        """
        Сравнение метаинформации о локальном объекте с метаинформацией объекта в хранилище

        Аргументы:
            meta (dict)   -- Метаинформация о локальном объекте
            stat (ydItem) -- Информация об оъекте

        Результат (dict):
            Метаинформация для изменения или None
        """
        if not stat or not getattr(stat, "custom_properties", None):
            return meta

        result = {}
        for key, value in iteritems(stat.custom_properties):
            if key in meta and meta[key] == value:
                continue
            result[key] = meta[key]

        return result if len(result) > 0 else None


    def meta_patch(self, source, target, stat):
        """
        Установка метаинформации для объекта в хранилище

        Аргументы:
            source (str)    -- Локальный объект
            target (str)    -- Объект в хранилище
            stat   (ydItem) -- Информация об объекте в хранилище или None
        """
        if self.options.attr and os.name != "nt":
            meta = self._meta(source)
            diff = self._meta_diff(meta, stat)
            if diff:
                self.patch(target, diff)


    def _ensure_remote(self, path, type, stat = None):
        """
        Метод проверки возможности создания объекта требуемого типа в хранилище.
        Если объект уже существует и типы не совпадают, производится удаление объекта.
        Если требуемый тип является директорией, то в случае ее отсутствия производится ее создание.

        Аргументы:
            path (str)    -- Объект в хранилище
            type (str)    -- Тип объекта в хранилище (file|dir)
            stat (ydItem) -- Информация об объекте (если уже имеется)

        Результат (ydItem):
            Метаинформация об объекте, если он уже существует и его тип совпадает с аргументом type.
        """
        if not (type == "dir" or type == "file"):
            raise ValueError("Unsupported type: {}".format(type))

        if stat == None:
            try:
                stat = self.stat(path)
            except ydError as e:
                if e.errno != 404:
                    raise

        if stat != None:
            if stat.type != type:
                self.delete(path)
                if type == "dir":
                    self.create(path)
            else:
                return stat
        elif type == "dir":
            self.create(path)

        return None


    def _put_sync(self, source, target):
        """
        Синхронизация локальных файлов и директорий с находящимися в хранилище

        Аргументы:
            source (str) -- Имя локальной директории (со слешем)
            target (str) -- Имя директории в хранилище (со слешем)
        """
        flist = self.list(target)

        for item in os.listdir(source):
            sitem = source + item
            titem = target + item

            if not os.path.islink(sitem):
                stat = None
                if os.path.isdir(sitem):
                    stat = self._ensure_remote(titem, "dir", flist[item] if item in flist else None)
                    self.meta_patch(sitem, titem, stat)
                    self._put_sync(sitem + "/", titem + "/")
                elif os.path.isfile(sitem):
                    force = True
                    if item in flist:
                        stat = self._ensure_remote(titem, "file", flist[item])
                        if not self.options.encrypt and stat and stat.isfile() and os.path.getsize(sitem) == stat.size and self.md5(sitem) == stat.md5:
                            force = False

                    if force:
                        self.put(sitem, titem)

                    self.meta_patch(sitem, titem, stat)
                else:
                    raise ydError(1, "Unsupported filesystem object: {0}".format(sitem))

                if item in flist:
                    del flist[item]
            else:
                self.verbose("Skip: {0}".format(sitem), self.options.verbose)

        if self.options.rsync:
            for item in itervalues(flist):
                self.delete(target + item.name)


    def _ensure_local(self, path, type):
        """
        Метод проверки возможности создания локального объекта требуемого типа.
        Если объект уже существует и типы не совпадают, производится удаление объекта.
        Если требуемый тип является директорией, то в случае ее отсутствия производится ее создание.

        Аргументы:
            path (str) -- Объект
            type (str) -- Тип объекта (file|dir)

        Результат (bool):
            True если объект нужного типа уже существует, иначе False
        """
        if not (type == "dir" or type == "file"):
            raise ValueError("Unsupported type: {0}".format(type))

        if os.path.exists(path):
            if os.path.islink(path):
                self.debug("rm {0}".format(path), self.options.debug)
                os.unlink(path)
                return False
            if type == "dir":
                if os.path.isdir(path):
                    return True
                elif os.path.isfile(path):
                    self.debug("rm {0}".format(path), self.options.debug)
                    os.remove(path)
                else:
                    raise ydError(1, "Unsupported filesystem object: {0}".format(path))
            elif type == "file":
                if os.path.isfile(path):
                    return True
                elif os.path.isdir(path):
                    self.debug("rm -r {0}".format(path), self.options.debug)
                    shutil.rmtree(path)
                else:
                    raise ydError(1, "Unsupported filesystem object: {0}".format(path))
        elif type == "dir":
            self.debug("mkdir {0}".format(path), self.options.debug)
            os.mkdir(path)
            return True

        return False


    def _get_sync(self, source, target):
        """
        Синхронизация файлов и директорий в хранилище с локальными

        Аргументы:
            source (str) -- Имя директории в хранилище (со слешем)
            target (str) -- Имя локальной директории (со слешем)
        """
        flist = self.list(source)

        for item in itervalues(flist):
            sitem = source + item.name
            titem = target + item.name

            if item.isdir():
                self._ensure_local(titem, "dir")
                self._get_sync(sitem + "/", titem + "/")
            elif item.isfile():
                force  = True
                exists = self._ensure_local(titem, "file")
                if not self.options.decrypt and exists and os.path.getsize(titem) == item.size and self.md5(titem) == item.md5:
                    force = False

                if force:
                    self.get(sitem, titem)

        if self.options.rsync:
            for item in os.listdir(target):
                if item not in flist:
                    titem = target + item
                    if os.path.islink(titem):
                        self.debug("rm {0}".format(titem), self.options.debug)
                        os.remove(titem)
                    elif os.path.isfile(titem):
                        self.debug("rm {0}".format(titem), self.options.debug)
                        os.remove(titem)
                    elif os.path.isdir(titem):
                        self.debug("rm -r {0}".format(titem), self.options.debug)
                        shutil.rmtree(titem)
                    else:
                        raise ydError(1, "Unsupported filesystem object: {0}".format(titem))


    def du(self, path, depth = 0):
        """
        Подсчет занимаемого места

        Аргументы:
            path  (str) -- Путь
            depth (int) -- Текущая глубина обхода

        Результат (list):
            Список [(имя, размер)] объектов
        """
        size   = 0
        result = []

        items = self.list(path)

        for item in itervalues(items):
            if item.isfile():
                size += item.size
            elif item.isdir():
                sub   = self.du(path + item.name + "/", depth + 1)
                size += sub[-1][1]
                if depth < self.options.depth:
                    result.extend(sub)

        result.append([path, size])

        return result


    def clean(self, path):
        """
        Очистка файлов и директорий

        Аргументы:
            path (str) -- Путь
        """
        if self.options.keep == "" or self.options.type not in ["all", "file", "dir"]:
            return

        flist = listvalues(self.list(path))

        if self.options.type != "all":
            tlist = []
            for item in flist:
                if item.type == self.options.type:
                    tlist.append(item)
            flist = tlist

        for item in flist:
            item.modified = dateutil.parser.parse(item.modified).astimezone(dateutil.tz.tzutc())

        flist.sort(key = lambda x: x.modified)

        if re.match("^[0-9]+$", self.options.keep, re.IGNORECASE) != None:
            self.verbose("Clean: <{0}> keep last {1}".format(self.options.type, self.options.keep), self.options.verbose)
            flist = flist[:-int(self.options.keep)]
        elif re.match("^[0-9]+[dwmy]$", self.options.keep, re.IGNORECASE):
            m = re.split("^([0-9]+)([dwmy])$", self.options.keep, re.IGNORECASE)
            if m != None and len(m) == 4:
                count    = int(m[1])
                interval = str(m[2])

                relative = None
                if interval == "d":
                    relative = dateutil.relativedelta.relativedelta(days = -count)
                elif interval == "w":
                    relative = dateutil.relativedelta.relativedelta(weeks = -count)
                elif interval == "m":
                    relative = dateutil.relativedelta.relativedelta(months = -count)
                elif interval == "y":
                    relative = dateutil.relativedelta.relativedelta(years = -count)

                relative = datetime.datetime.now(dateutil.tz.tzutc()).replace(microsecond = 0) + relative

                self.verbose("Clean: <{0}> before {1}".format(self.options.type, relative.isoformat()), self.options.verbose)

                tlist = []
                for item in flist:
                    if item.modified < relative:
                        tlist.append(item)

                flist = tlist
        elif len(self.options.keep) >= 10:   # YYYY-MM-DD
            relative =  dateutil.parser.parse(self.options.keep).astimezone(dateutil.tz.tzutc())

            self.verbose("Clean: <{0}> before {1}".format(self.options.type, relative.isoformat()), self.options.verbose)

            tlist = []
            for item in flist:
                if item.modified < relative:
                    tlist.append(item)

            flist = tlist
        else:
            return

        for item in flist:
            if self.options.dry:
                ydBase.echo("{0:>25} {1:>7} {2}".format(item.modified.isoformat(), "<{0}>".format(item.type), item.name))
            else:
                self.delete(path + item.name)


class ydCmd(ydExtended):
    """
    Обработчики команд
    """
    def __init__(self, options):
        """
        Аргументы:
            options (ydOptions) -- Опции приложения
        """
        ydExtended.__init__(self, options)


    @staticmethod
    def human(val):
        """
        Преобразование числа байт в человекочитаемый вид

        Аргументы:
            val (int) -- Значение в байтах

        Результат (str):
            Человекочитаемое значение с размерностью
        """
        if val < 1024:
            return "{0}".format(val)
        elif val < 1024 * 1024:
            return "{0:.0f}K".format(val / 1024)
        elif val < 1024 * 1024 * 1024:
            return "{0:.0f}M".format(val / 1024 / 1024)
        elif val < 1024 * 1024 * 1024 * 1024:
            return "{0:.0f}G".format(val / 1024 / 1024 / 1024)

        return "{0:.0f}T".format(val / 1024 / 1024 / 1024 / 1024)


    @staticmethod
    def remote_path(path):
        """
        Конвертация облачного пути в канонический

        Аргументы:
            path (str) -- Путь в хранилище

        Результат (str):
            Канонический путь вида disk:/path
        """
        if path.find("disk:") != 0:
            if path[0] != "/":
                path = "/{0}".format(path)
            path = "disk:{0}".format(path)

        return path


    def info_cmd(self, args):
        """
        Вывод метаинформации о хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 0:
            raise ydError(1, "Too many arguments")

        result = self.info()

        result["used_space_pct"] = int(result["used_space"]) * 100 / int(result["total_space"])

        if self.options.human:
            result["used_space"]  = self.human(result["used_space"])
            result["total_space"] = self.human(result["total_space"])

        ydBase.echo("{0:>7}: {1} ({2:.0f}%)".format("Used", result["used_space"], result["used_space_pct"]))
        ydBase.echo("{0:>7}: {1}".format("Total", result["total_space"]))


    def stat_cmd(self, args):
        """
        Вывод метаинформации об объекте в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        path = "/"
        if len(args) > 0:
            path = args[0]

        ydBase.echo(self.stat(self.remote_path(path)))


    def list_cmd(self, args):
        """
        Вывод списка файлов и директорий в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        path = "/"
        if len(args) > 0:
            path = args[0]

        result = listvalues(self.list(self.remote_path(path)))
        result.sort(key = lambda x: (x.type, x.name))

        for item in result:
            if item.isdir():
                size = "<dir>"
            elif self.options.human:
                size = self.human(item.size)
            else:
                size = item.size

            if self.options.long:
                ydBase.echo("{0} {1:>26} {2:>11} {3}".format(item.created, item.modified, size, item.name))
            elif self.options.short:
                ydBase.echo("{0}".format(item.name))
            else:
                ydBase.echo("{0:>5}  {1}".format(size, item.name))


    def last_cmd(self, args):
        """
        Вывод метаинформации о последних загруженных файлах

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        limit = 0
        if len(args) > 0:
            try:
                limit = int(args[0])
                if limit < 1:
                    raise ydError(1, "Limit must be greater than zero")
            except ValueError:
                raise ydError(1, "Limit must be integer")

        result = listvalues(self.last(limit))
        result.sort(key = lambda x: (x.modified, x.created, x.name))

        for item in result:
            if self.options.human:
                size = self.human(item.size)
            else:
                size = item.size

            if self.options.long:
                ydBase.echo("{0} {1:>26} {2:>11} {3}".format(item.created, item.modified, size, item.path[5:]))
            elif self.options.short:
                ydBase.echo("{0}".format(item.path[5:]))
            else:
                ydBase.echo("{0:>5}  {1}".format(size, item.path[5:]))


    def delete_cmd(self, args):
        """
        Обработчик удаления объекта хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "File or directory not specified")

        for arg in args:
            self.delete(self.remote_path(arg))


    def copy_cmd(self, args):
        """
        Обработчик копироавния объекта в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 2:
            raise ydError(1, "Source or target not specified")
        if len(args) > 2:
            raise ydError(1, "Too many arguments")

        source = args[0]
        target = args[1]

        self.copy(self.remote_path(source), self.remote_path(target))


    def move_cmd(self, args):
        """
        Обработчик перемещения объекта в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 2:
            raise ydError(1, "Source or target not specified")
        if len(args) > 2:
            raise ydError(1, "Too many arguments")

        source = args[0]
        target = args[1]

        self.move(self.remote_path(source), self.remote_path(target))


    def create_cmd(self, args):
        """
        Обработчик создания директории в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "Directory name not specified")

        for arg in args:
            self.create(self.remote_path(arg))


    def share_cmd(self, args):
        """
        Обработчик публикации объекта (объект становится доступен по прямой ссылке)

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "Object name not specified")

        for arg in args:
            info = self.publish(self.remote_path(arg))
            ydBase.echo("{0} -> {1}".format(info.path, info.public_url))


    def revoke_cmd(self, args):
        """
        Обработчик закрытия публичного доступа к объекту (объект становится недоступен по прямой ссылке)

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "Object name not specified")

        for arg in args:
            self.unpublish(self.remote_path(arg))


    def put_cmd(self, args):
        """
        Обработчик загрузки файла в хранилище

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "Source not specified")
        if len(args) > 2:
            raise ydError(1, "Too many arguments")

        source = args[0]

        if len(args) == 2:
            target = args[1]
        else:
            target = "/"

        if os.path.basename(target) == "":
            target += os.path.basename(source)

        if not os.path.islink(source):
            target = self.remote_path(target)
            if os.path.isdir(source):
                if os.path.basename(source) != "":
                    source += "/"
                if os.path.basename(target) != "":
                    target += "/"
                stat = self._ensure_remote(target, "dir")
                self.meta_patch(source, target, stat)
                self._put_sync(source, target)
            elif os.path.isfile(source):
                force = True
                stat  = self._ensure_remote(target, "file")
                if not self.options.encrypt and stat and stat.isfile() and os.path.getsize(source) == stat.size and self.md5(source) == stat.md5:
                    force = False
                if force:
                    self.put(source, target)
                self.meta_patch(source, target, stat)
            else:
                raise ydError(1, "Unsupported filesystem object: {0}".format(source))
        else:
            self.verbose("Skip: {0}".format(source), self.options.verbose)


    def get_cmd(self, args):
        """
        Обработчик получения файла из хранилища

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) < 1:
            raise ydError(1, "Source not specified")
        if len(args) > 2:
            raise ydError(1, "Too many arguments")

        source = self.remote_path(args[0])

        if len(args) == 2:
            target = args[1]
        else:
            target = os.path.basename(source)

        stat = self.stat(source)

        if stat.isdir():
            if target == "":
                target = "."
            if os.path.basename(source) != "":
                source += "/"
            if os.path.basename(target) != "":
                target += "/"

            self._ensure_local(target, "dir")
            self._get_sync(source, target)
        elif stat.isfile():
            force  = True
            exists = self._ensure_local(target, "file")
            if not self.options.decrypt and exists and os.path.getsize(target) == stat.size and self.md5(target) == stat.md5:
                force = False
            if force:
                self.get(source, target)


    def du_cmd(self, args):
        """
        Обработчик оценки занимаемого места

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        if len(args) == 1:
            path = args[0]
        else:
            path = "/"

        if os.path.basename(path) != "":
            path += "/"

        result = self.du(self.remote_path(path))

        for name, size in result:
            name = name[5:-1]
            if len(name) == 0:
                name = "/"
            if options.human:
                ydBase.echo("{0:>5}  {1}".format(self.human(size), name))
            else:
                ydBase.echo("{0:>11}  {1}".format(size, name))


    def clean_cmd(self, args):
        """
        Обработчик очистки файлов и директорий

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        if len(args) == 1:
            path = args[0]
        else:
            path = "/"

        if os.path.basename(path) != "":
            path += "/"

        self.clean(path)


    def token_cmd(self, args):
        """
        Получение OAuth токена для приложения

        Аргументы:
            args (dict) -- Аргументы командной строки
        """
        if len(args) > 1:
            raise ydError(1, "Too many arguments")

        if len(args) == 0:
            ydBase.echo("Open URL below in your browser, allow access and paste code as argument")
            ydBase.echo("https://oauth.yandex.com/authorize?response_type=code&client_id={0}".format(self.options.appid))
            return

        method  = "POST"
        url     = "https://oauth.yandex.com/token"
        data    = "grant_type=authorization_code&code={0}&client_id={1}&client_secret={2}".format(args[0], self.options.appid, self.options.appsecret)
        headers = self._headers()

        headers["Content-Type"]   = "application/x-www-form-urlencoded"
        headers["Content-Length"] = len(data)

        del headers["Authorization"]

        result = self.query_retry(method, url, None, headers, None, data)

        ydBase.echo("OAuth token is: {0}".format(result["access_token"]))


    @staticmethod
    def print_usage(cmd = None):
        """
        Вывод справки об использовании приложения и завершение работы

        Аргументы:
            cmd (str) -- Имя команды для которой выводится справка (пустое значение для справки по командам)
        """
        default = ydConfig.default_config()
        if cmd == None or cmd == "help":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} <command> [options] [args]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Commands:")
            ydBase.echo("     help   -- describe the usage of this program or its subcommands")
            ydBase.echo("     ls     -- list files and directories")
            ydBase.echo("     rm     -- remove file or directory")
            ydBase.echo("     cp     -- copy file or directory")
            ydBase.echo("     mv     -- move file or directory")
            ydBase.echo("     put    -- upload file to storage")
            ydBase.echo("     get    -- download file from storage")
            ydBase.echo("     mkdir  -- create directory")
            ydBase.echo("     stat   -- show metainformation about cloud object")
            ydBase.echo("     info   -- show metainformation about cloud storage")
            ydBase.echo("     last   -- show metainformation about last uploaded files")
            ydBase.echo("     share  -- publish uploaded object")
            ydBase.echo("     revoke -- unpublish uploaded object")
            ydBase.echo("     du     -- estimate files space usage")
            ydBase.echo("     clean  -- delete old files and/or directories")
            ydBase.echo("     token  -- get oauth token for application")
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --timeout=<N> -- timeout for api requests in seconds (default: {0})".format(default["timeout"]))
            ydBase.echo("     --retries=<N> -- api call retries count (default: {0})".format(default["retries"]))
            ydBase.echo("     --delay=<N>   -- api call delay between retries in seconds (default: {0})".format(default["delay"]))
            ydBase.echo("     --limit=<N>   -- limit rows by one api call for listing files and directories (default: {0})".format(default["limit"]))
            ydBase.echo("     --token=<S>   -- oauth token (default: none)")
            ydBase.echo("     --quiet       -- suppress all errors (default: {0})".format(default["quiet"]))
            ydBase.echo("     --verbose     -- verbose output (default: {0})".format(default["verbose"]))
            ydBase.echo("     --debug       -- debug output (default: {0})".format(default["debug"]))
            ydBase.echo("     --chunk=<N>   -- chunk size in KB for io operations (default: {0})".format(default["chunk"]))
            ydBase.echo("     --ca-file=<S> -- file with trusted CAs (default: {0})".format("none" if not default["ca-file"] else default["ca-file"]))
            ydBase.echo("     --ciphers=<S> -- ciphers sute (default: {0})".format("none" if not default["ciphers"] else default["ciphers"]))
            ydBase.echo("")
        elif cmd == "ls":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} ls [options] [disk:/object]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --human -- human-readable file size")
            ydBase.echo("     --short -- short format (names only)")
            ydBase.echo("     --long  -- long format (created, modified, size, name)")
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, target will be root '/' directory")
            ydBase.echo("")
        elif cmd == "rm":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} rm <disk:/object1> [disk:/object2] ...".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --poll=<N> -- poll time interval in seconds for asynchronous operations (default: {0})".format(default["poll"]))
            ydBase.echo("     --async    -- do not wait (poll cheks) for completion (default: {0})".format(default["async"]))
            ydBase.echo("")
        elif cmd == "cp":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} cp <disk:/object1> <disk:/object2>".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --poll=<N> -- poll time interval in seconds for asynchronous operations (default: {0})".format(default["poll"]))
            ydBase.echo("     --async    -- do not wait (poll cheks) for completion (default: {0})".format(default["async"]))
            ydBase.echo("")
        elif cmd == "mv":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} mv <disk:/object1> <disk:/object2>".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --poll=<N> -- poll time interval in seconds for asynchronous operations (default: {0})".format(default["poll"]))
            ydBase.echo("     --async    -- do not wait (poll cheks) for completion (default: {0})".format(default["async"]))
            ydBase.echo("")
        elif cmd == "put":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} put <file> [disk:/object]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --rsync       -- sync remote tree with local")
            ydBase.echo("     --encrypt     -- encrypt uploaded files using --encrypt-cmd (default: {0})".format(default["encrypt"]))
            ydBase.echo("     --encrypt-cmd -- command used to encrypt local file passed to stdin and upload from stdout (default: none)")
            ydBase.echo("     --temp-dir    -- directory to store encrypted temporary files (default: system default)")
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, target will be root '/' directory")
            ydBase.echo(" * If target specify a directory (ended with '/'), source file name will be added")
            ydBase.echo(" * If target file exists, it will be silently overwritten")
            ydBase.echo(" * Symbolic links are ignored")
            ydBase.echo("")
        elif cmd == "get":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} get <disk:/object> [file]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --rsync       -- sync local tree with remote")
            ydBase.echo("     --decrypt     -- decrypt downloaded files using --decrypt-cmd (default: {0})".format(default["decrypt"]))
            ydBase.echo("     --decrypt-cmd -- command used to decrypt downloaded file passed to stdin and store from stdout (default: none)")
            ydBase.echo("     --temp-dir    -- directory to store encrypted temporary files (default: system default)")
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, source file name will be used")
            ydBase.echo(" * If target exists, it will be silently overwritten")
            ydBase.echo("")
        elif cmd == "mkdir":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} mkdir <disk:/path1> [disk:/path2] ...".format(sys.argv[0]))
            ydBase.echo("")
        elif cmd == "stat":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} stat [disk:/object]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, target will be root '/' directory")
            ydBase.echo("")
        elif cmd == "info":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} info".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --long -- show sizes in bytes instead human-readable format")
            ydBase.echo("")
        elif cmd == "last":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} last [N]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --human -- human-readable file size")
            ydBase.echo("     --short -- short format (names only)")
            ydBase.echo("     --long  -- long format (created, modified, size, name)")
            ydBase.echo("")
            ydBase.echo(" * If argument N is not specified, default REST API value will be used.")
            ydBase.echo("")
        elif cmd == "share":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} share <disk:/object1> [disk:/object2] ...".format(sys.argv[0]))
            ydBase.echo("")
        elif cmd == "revoke":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} revoke <disk:/object1> [disk:/object2] ...".format(sys.argv[0]))
            ydBase.echo("")
        elif cmd == "du":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} du [disk:/object]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --depth=<N> -- show size if dir is N or fewer levels below target (default: {0})".format(default["depth"]))
            ydBase.echo("     --long      -- show sizes in bytes instead human-readable format")
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, target will be root '/' directory")
            ydBase.echo("")
        elif cmd == "clean":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} clean <options> [disk:/object]".format(sys.argv[0]))
            ydBase.echo("")
            ydBase.echo("Options:")
            ydBase.echo("     --dry      -- just print list of object to delete (default: {0})".format(default["dry"]))
            ydBase.echo("     --type=<S> -- type of objects - 'file', 'dir' or 'all' (default: {0})".format(default["type"]))
            ydBase.echo("     --keep=<S> -- keep criteria (default: none):")
            ydBase.echo("                   * date ('2014-02-12T12:19:05+04:00')")
            ydBase.echo("                   * relative interval ('7d', '4w', '1m', '1y')")
            ydBase.echo("                   * number of objects ('31')")
            ydBase.echo("")
            ydBase.echo(" * If target is not specified, target will be root '/' directory")
            ydBase.echo(" * Objects sorted and filtered by modified date (not created date)")
            ydBase.echo("")
        elif cmd == "token":
            ydBase.echo("Usage:")
            ydBase.echo("     {0} token [code]".format(sys.argv[0]))
            ydBase.echo("")
        else:
            sys.stderr.write("Unknown command {0}\n".format(cmd))
            sys.exit(1)

        sys.exit(0)


if __name__ == "__main__":
    argc = len(sys.argv)
    if argc < 2:
        ydCmd.print_usage()

    config = ydConfig.load_config()

    args = []
    for i in range(1, argc):
        arg = sys.argv[i]
        opt = re.split("^--(\S+?)(=(.*)){,1}$", arg)
        if len(opt) == 5:
            if opt[3] == None:
                opt[3] = True
            config[opt[1].lower()] = opt[3]
        else:
            args.append(arg)

    if len(args) == 0:
        ydCmd.print_usage()

    options = ydOptions(config)

    command = args.pop(0).lower()
    if command == "help":
        command = None
        if argc > 2:
            command = args.pop(0).lower()
        ydCmd.print_usage(command)

    if options.cafile == None:
        ydBase.verbose("Unsafe HTTPS connection - ca-file not used", options.verbose)

    try:
        cmd = ydCmd(options)
        if command == "ls":
            cmd.list_cmd(args)
        elif command == "rm":
            cmd.delete_cmd(args)
        elif command == "cp":
            cmd.copy_cmd(args)
        elif command == "mv":
            cmd.move_cmd(args)
        elif command == "put":
            cmd.put_cmd(args)
        elif command == "get":
            cmd.get_cmd(args)
        elif command == "mkdir":
            cmd.create_cmd(args)
        elif command == "stat":
            cmd.stat_cmd(args)
        elif command == "info":
            cmd.info_cmd(args)
        elif command == "last":
            cmd.last_cmd(args)
        elif command == "share":
            cmd.share_cmd(args)
        elif command == "revoke":
            cmd.revoke_cmd(args)
        elif command == "du":
            cmd.du_cmd(args)
        elif command == "clean":
            cmd.clean_cmd(args)
        elif command == "token":
            cmd.token_cmd(args)
        else:
            ydCmd.print_usage(command)
    except ydError as e:
        if not options.quiet:
            sys.stderr.write("{0}\n".format(e.errmsg))
        sys.exit(e.errno if e.errno < 256 else int(e.errno / 100))
    except ydCertError as e:
        if not options.quiet:
            sys.stderr.write("{0}\n".format(e))
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(1)
