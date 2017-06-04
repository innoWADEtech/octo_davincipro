import logging
import os
from io import BytesIO
from collections import namedtuple

log = logging.getLogger(__name__)

class GCodeBlankLine(object):
    def __str__(self):
        return ""


class GCodeTranslations(object):
    @classmethod
    def translate_davincijr10(cls, gcode, keywords):
        newcode = []
        for code in gcode:
            if not hasattr(code, "statement"):
                newcode.append(code)
                continue
            if code.statement.startswith("G0 "):
                # DaVinci doesn't use G0 so we make them G1
                statement = code.statement.replace("G0 ", "G1 ")
            else:
                statement = code.statement
            newcode.append(GCodeStatement(statement))
        return newcode


class GCodeComment(object):
    @classmethod
    def from_string(cls, string):
        return cls(string)

    def __init__(self, line):
        self.line = line

    def __str__(self):
        return self.line


class GCodeStatement(object):
    @classmethod
    def from_string(cls, string):
        return cls(string)

    def __init__(self, statement):
        self.statement = statement

    def __str__(self):
        return self.statement

class GCodeFile(object):
    @classmethod
    def from_file(cls, path):
        with open(path, 'r') as f:
            return cls.from_string(f.read())

    @classmethod
    def from_string(cls, string):
        gcode = [] 
        for line in BytesIO(string):
            line = line.strip()
            if not line:
                gcode.append(GCodeBlankLine())
                continue
            if line.startswith(";"):
                gcode.append(GCodeComment.from_string(line))
            elif line:
                gcode.append(GCodeStatement.from_string(line))
        return cls(gcode)


    def __init__(self, statements):
        self.statements = statements

    @property
    def headers(self):
        return [code for code in self.statements if isinstance(code, GCodeComment)]

    @property
    def gcode(self):
        return [code for code in self.statements if not isinstance(code, GCodeComment)]

    @property
    def text(self):
        """
        Return the content of the GCode file as a string.
        """
        return os.linesep.join(str(s) for s in self.statements)

    @property
    def header_text(self):
        """
        Return the headers of the file as a string.
        """
        return os.linesep.join(map(str, self.headers))

    @property
    def gcode_text(self):
        """
        Return the gcode statements of the file as a string.
        """
        return os.linesep.join(map(str, self.gcode))

    def write(self, path):
        log.debug("Writing output file: {}".format(path))
        with open(path, "w") as f:
            for item in self.statements:
                f.write(str(item))
                f.write(os.linesep)


