%%http://www.jfm.damtp.cam.ac.uk/online_submission.html%%
%% This is file `jfm.cls'
%%
%% CUP Journal of Fluid Mechanics document class
%% Copyright (1996, 1997) Cambridge University Press
%%
%% by Mark A. Reed
%%   based on JFM.sty v1.3.
%% v1.25 8 Aug 2001 revised by Alison Woollatt to include DOI reference
%% v1.26 released 27th July 2004
%% v1.27 13 Nov 2006 modified by TeX Support to remove "By" from authors
%% v1.28 13 Mar 2007 modified by TeX Support to change \floatpagefraction
%% from {.95} to {.9}
%%
%% Incorporating parts of authordate.sty, by David Rhead.
%% Incorporating subeqn.sty, by Stephen Gildea.
%% Incorporating subeqnarray.sty, by Johannes Braams.
%%
%% Bugs (in the case of unchanged files) should be reported to
%% texsupport@aptaracorp.com
%%
%% This software may only be used in the preparation of journal articles
%% or books or parts of books to be published by Cambridge University Press.
%% Any other use constitutes an infringement of copyright.
%%
%% \CharacterTable
%%  {Upper-case    \A\B\C\D\E\F\G\H\I\J\K\L\M\N\O\P\Q\R\S\T\U\V\W\X\Y\Z
%%   Lower-case    \a\b\c\d\e\f\g\h\i\j\k\l\m\n\o\p\q\r\s\t\u\v\w\x\y\z
%%   Digits        \0\1\2\3\4\5\6\7\8\9
%%   Exclamation   \!     Double quote  \"     Hash (number) \#
%%   Dollar        \$     Percent       \%     Ampersand     \&
%%   Acute accent  \'     Left paren    \(     Right paren   \)
%%   Asterisk      \*     Plus          \+     Comma         \,
%%   Minus         \-     Point         \.     Solidus       \/
%%   Colon         \:     Semicolon     \;     Less than     \<
%%   Equals        \=     Greater than  \>     Question mark \?
%%   Commercial at \@     Left bracket  \[     Backslash     \\
%%   Right bracket \]     Circumflex    \^     Underscore    \_
%%   Grave accent  \`     Left brace    \{     Vertical bar  \|
%%   Right brace   \}     Tilde         \~}
%%

\NeedsTeXFormat{LaTeX2e}[1996/06/01]
\ProvidesClass{jfm}[2006/11/13 v1.27 Journal of Fluid Mechanics document class]

\usepackage{graphicx}

\newif\ifNAT@numbers\NAT@numbersfalse
\AtBeginDocument{\usepackage{natbib}}

\newif\if@index
\newif\if@referee
\newif\ifCUPmtlplainloaded
\newif\ifflm@rapids
\newif\iflineno% 3-8-20
\DeclareOption{lineno}{\linenotrue}% 3-8-20

\DeclareOption{oneside}{\relax}
\DeclareOption{twoside}{\@twosidetrue \@mparswitchtrue}
\DeclareOption{draft}{\setlength\overfullrule{5\p@}}
\DeclareOption{final}{\setlength\overfullrule{\z@}}
\DeclareOption{onecolumn}{\@twocolumnfalse}
\DeclareOption{twocolumn}{\relax}
\DeclareOption{titlepage}{\relax}
\DeclareOption{notitlepage}{\relax}
\DeclareOption{leqno}{\relax}
\DeclareOption{fleqn}{\relax}
\DeclareOption{index}{\@indextrue}
\DeclareOption{prodtf}{\CUPmtlplainloadedtrue}
\DeclareOption{referee}{\@refereetrue}
\DeclareOption{rapids}{\global\flm@rapidstrue}

\ExecuteOptions{twoside,final,onecolumn}
\ProcessOptions\relax

\ifCUPmtlplainloaded \RequirePackage{CUPTimes,jfm2esym}\fi

\setlength\lineskip{1\p@}
\setlength\normallineskip{1\p@}
\renewcommand\baselinestretch{}

\edef\t@xtsize{10.5}% 8-8-20 %\edef\t@xtsize{\ifCUPmtlplainloaded 10.5\else 10\fi}


\renewcommand\normalsize{%
  \@setfontsize\normalsize{\t@xtsize}\@xiipt
  \abovedisplayskip 6.5\p@ \@plus 1\p@ \@minus 1\p@
  \belowdisplayskip \abovedisplayskip
  \abovedisplayshortskip 3\p@ \@plus 1\p@
  \belowdisplayshortskip \abovedisplayshortskip
}

\normalsize



\let\fontswitch=\relax
\let\realbf=\relax

\AtBeginDocument{%
  \ifuseAMSsubequ \else
    \global\let\subequations\CUPsubequations
    \global\let\endsubequations\endCUPsubequations
  \fi
}

\AtBeginDocument{%
  \@ifpackageloaded{natbib}
    {\bibpunct{(}{)}{;}{a}{}{,}%
     \global\let\thebibliography\JFMthebib
     \global\let\endthebibliography\JFMendthebib}
    {\relax}%
}

\ifCUPmtlplainloaded
  \AtBeginDocument{%
    \DeclareMathSizes{10.5}{10.5}{7}{5}%
    \DeclareFontShape{OT1}{mtr}{sb}{n}{<-> xmntsm}{}%
    \DeclareMathAlphabet{\sbmath}{OT1}{mtr}{sb}{n}%
    \newcommand\realbf{\def\bfdefault{bx}\bfseries}%
    \newcommand\fontswitch{\def\bfdefault{sb}}%
  }
\fi

\newcommand\small{%
  \@setfontsize\small\@ixpt\@xpt
  \abovedisplayskip 6\p@ \@plus 1\p@ \@minus 1\p@
  \belowdisplayskip \abovedisplayskip
  \abovedisplayshortskip 3\p@ \@plus 1\p@
  \belowdisplayshortskip \abovedisplayshortskip
}

\newcommand\footnotesize{\small}
\newcommand\indexsize{\@setfontsize\indexsize\@viiipt\@ixpt}
\newcommand\scriptsize{\@setfontsize\scriptsize\@viipt\@viiipt}
\newcommand\tiny{\@setfontsize\tiny\@vpt\@vipt}
\newcommand\large{\@setfontsize\large\@xipt{13}}
\newcommand\Large{\@setfontsize\Large\@xivpt{18}}
\newcommand\LARGE{\@setfontsize\LARGE\@xviipt{19}}
\newcommand\huge{\@setfontsize\huge\@xxpt{25}}
\newcommand\Huge{\@setfontsize\Huge\@xxvpt{30}}

\DeclareOldFontCommand{\rm}{\normalfont\rmfamily}{\mathrm}
\DeclareOldFontCommand{\sf}{\normalfont\sffamily}{\mathsf}
\DeclareOldFontCommand{\tt}{\normalfont\ttfamily}{\mathtt}
\DeclareOldFontCommand{\bf}{\normalfont\bfseries}{\mathbf}
\DeclareOldFontCommand{\it}{\normalfont\itshape}{\mathit}
\DeclareOldFontCommand{\sl}{\normalfont\slshape}{\@nomath\sl}
\DeclareOldFontCommand{\sc}{\normalfont\scshape}{\@nomath\sc}
\DeclareRobustCommand*\cal{\@fontswitch\relax\mathcal}
\DeclareRobustCommand*\mit{\@fontswitch\relax\mathnormal}

\edef\r@{\ifCUPmtlplainloaded mtr\else cmr\fi}
\edef\s@{\ifCUPmtlplainloaded mtss\else cmss\fi}

\newcommand\qsmall{%
  \usefont{OT1}{\r@}{m}{n}\fontsize{9.75}{\f@baselineskip}\selectfont}
\newcommand\qsmit{%
  \usefont{OT1}{\r@}{m}{it}\fontsize{9.75}{\f@baselineskip}\selectfont}
\newcommand\qsbf{%
  \usefont{OT1}{\r@}{bx}{n}\fontsize{9.75}{\f@baselineskip}\selectfont}
\newcommand\qssf{%
  \usefont{OT1}{\s@}{m}{n}\fontsize{9.75}{\f@baselineskip}\selectfont}
\newcommand\boldit{%
  \usefont{OT1}{\r@}{bx}{it}\fontsize{10}{\f@baselineskip}\selectfont}

\newcommand\qit{\qsmit \fontsize{\f@size}{10.75}\selectfont}
\newcommand\qbf{\qsbf  \fontsize{\f@size}{10.75}\selectfont}
\newcommand\qsf{\qssf  \fontsize{\f@size}{10.75}\selectfont}
\newcommand\qrm{\qsmall\fontsize{\f@size}{10.75}\selectfont}

\ifCUPmtlplainloaded\else
  \DeclareTextFontCommand\textsfi{\usefont{OT1}{cmss}{m}{sl}}
  \DeclareMathAlphabet\mathsfi            {OT1}{cmss}{m}{sl}
  \DeclareTextFontCommand\textsfb{\usefont{OT1}{cmss}{bx}{n}}
  \DeclareMathAlphabet\mathsfb            {OT1}{cmss}{bx}{n}
  \DeclareTextFontCommand\textsfbi{\usefont{OT1}{cmss}{m}{sl}}
  \DeclareMathAlphabet\mathsfbi            {OT1}{cmss}{m}{sl}
  \IfFileExists{t1phv.fd}
  {\DeclareTextFontCommand\textsfbi{\usefont{T1}{phv}{b}{it}}
  \DeclareMathAlphabet\mathsfbi            {T1}{phv}{b}{it}
  }{}
  \IfFileExists{ot1phv.fd}
  {\DeclareTextFontCommand\textsfbi{\usefont{OT1}{phv}{b}{it}}
  \DeclareMathAlphabet\mathsfbi            {OT1}{phv}{b}{it}
  }{}
\fi

%\DeclareMathAlphabet{\cup@mathbisf}{T1}{phv}{b}{it}

\DeclareMathSymbol{\varGamma}{\mathord}{letters}{"00}
\DeclareMathSymbol{\varDelta}{\mathord}{letters}{"01}
\DeclareMathSymbol{\varTheta}{\mathord}{letters}{"02}
\DeclareMathSymbol{\varLambda}{\mathord}{letters}{"03}
\DeclareMathSymbol{\varXi}{\mathord}{letters}{"04}
\DeclareMathSymbol{\varPi}{\mathord}{letters}{"05}
\DeclareMathSymbol{\varSigma}{\mathord}{letters}{"06}
\DeclareMathSymbol{\varUpsilon}{\mathord}{letters}{"07}
\DeclareMathSymbol{\varPhi}{\mathord}{letters}{"08}
\DeclareMathSymbol{\varPsi}{\mathord}{letters}{"09}
\DeclareMathSymbol{\varOmega}{\mathord}{letters}{"0A}


\setlength\oddsidemargin{2pc}
\setlength\evensidemargin{2pc}
\setlength\marginparwidth{2.0cm}
\setlength\marginparsep{10\p@}

\setlength\topmargin{2.5pc}
\setlength\headheight{12\p@}
\setlength\headsep{6\p@}
\setlength\topskip{12\p@}
\setlength\footskip{28pt}

\newlength\halflineskip
\setlength\halflineskip{6\p@ \@plus .5\p@ \@minus .5\p@}
\newlength\affilskip
\setlength\affilskip{3\p@}

\setlength\textheight{49\baselineskip}
\addtolength\textheight{\topskip}
\setlength\textwidth{32pc}
\setlength\columnsep{10\p@}
\setlength\columnseprule{\z@}

\special{papersize=174mm,247mm}
\pdfpagewidth 174mm
\pdfpageheight 247mm

\setlength\oddsidemargin{-1pc}
\setlength\evensidemargin{-1pc}
\setlength\topmargin{-2.7pc}


\setlength\footnotesep{\z@}
\setlength{\skip\footins}{9\p@ \@plus 3\p@}

\setlength\floatsep{10\p@ \@plus 2\p@ \@minus 1\p@}
\setlength\textfloatsep{12\p@ \@plus 6\p@}
\setlength\intextsep{\floatsep}
\setlength\dblfloatsep{\floatsep}
\setlength\dbltextfloatsep{\floatsep}
\setlength\@fptop{\z@ \@plus 0fil}
\setlength\@fpsep{10\p@ \@plus 0fil}
\setlength\@fpbot{\z@ \@plus 3fil}
\setlength\@dblfptop{\z@ \@plus 0fil}
\setlength\@dblfpsep{10\p@ \@plus 0fil}
\setlength\@dblfpbot{\z@ \@plus 3fil}
\setlength\marginparpush{5\p@}

\setlength\parskip{\z@ \@plus .3\p@}
\setlength\parindent{10pt}
\setlength\partopsep{\z@ \@plus 1\p@}
\@lowpenalty   51
\@medpenalty  151
\@highpenalty 301
\@beginparpenalty -\@lowpenalty
\@endparpenalty -\@lowpenalty
\@itempenalty -\@lowpenalty
\clubpenalty\z@
\widowpenalty\@M

\newcommand\partname{Part}
\newcommand\part{\par\addvspace{4ex}\@afterindentfalse \secdef\@part\@spart}

\def\@part[#1]#2{%
  \ifnum \c@secnumdepth >\m@ne
    \refstepcounter{part}%
    \addcontentsline{toc}{part}{\partname\ \thepart: #1}%
  \else
    \addcontentsline{toc}{part}{#1}%
  \fi
  {\parindent \z@ \centering
   \ifnum \c@secnumdepth >\m@ne
     \normalfont\large\rmfamily \MakeUppercase{\partname}\ %
     \ifcase\thepart \or ONE \or TWO \or THREE \or FOUR \or FIVE
       \or SIX \or SEVEN \or EIGHT \or NINE \or TEN \else \fi
   \par \nobreak
   \fi
   \normalfont\LARGE\rmfamily #2 \markboth{}{}\par}%
  \nobreak \vskip 3ex \@afterheading
}

\def\@spart#1{%
  {\parindent \z@ \centering\normalfont\LARGE\rmfamily #1\par}%
  \nobreak \vskip 3ex \@afterheading
}

\newcommand\@raggedright{\rightskip=\@flushglue \let\\=\@centercr
  \parindent\z@}
\newcommand\@raggedcenter{\centering\rightskip=\@flushglue
  \let\\=\@centercr}

\newif\ifno@eqnreset
\newcommand\nosectioneqnreset{\global\no@eqnresettrue
  \renewcommand\theequation{\@arabic\c@equation}%
}

\newcommand\section{%
  \ifno@eqnreset
  %\ifappendix\setcounter{section}{0}
    \ifappendix \setcounter{equation}\z@\fi
  \else
 % \setcounter{equation}{0}
   \setcounter{equation}\z@
  \fi
  \@startsection {section}{1}{\z@}
    {\ifflm@rapids 12\p@ \@plus 6\p@ \@minus 2\p@\else
     20\p@ \@plus 6\p@ \@minus 2\p@\fi}
    {3\p@}
    {\normalfont\large\ifflm@rapids\normalsize\fi\fontswitch\bfseries\@raggedright}%
}

\newcommand\subsection{%
  \@startsection{subsection}{2}{\z@}
    {12\p@ \@plus 3\p@ \@minus 3\p@}
    {3\p@}
    {\normalfont\normalsize\itshape\@raggedcenter}%
}

\newcommand\subsubsection{%
  \@startsection{subsubsection}{3}{\z@}
    {9\p@ \@plus 3\p@ \@minus 3\p@}
    {3\p@}
    {\raggedright\normalfont\normalsize\itshape}%
}


%\newcommand\paragraph{}
\newcommand\subparagraph{}

\def\@seccntformat#1{% FROM LATEX.LTX
  \normalfont\rmfamily\csname the#1\endcsname.\enskip
}

\def\@secappcntformat#1{%
  \ifappendix \appendixname\ifoneappendix\else~\fi\fi
  \ifoneappendix\else \csname the#1\endcsname\relax\fi
  \ifx\apphe@d\@empty \else .\fi\enskip
}

\def\@sect#1#2#3#4#5#6[#7]#8{% FROM LATEX.LTX
  \ifnum #2>\c@secnumdepth
    \let\@svsec\@empty
  \else
    \refstepcounter{#1}%
    \ifnum #2>\@ne
      \protected@edef\@svsec{\@seccntformat{#1}\relax}%
    \else
      \def\apphe@d{#8}%
      \protected@edef\@svsec{\@secappcntformat{#1}\relax}%
    \fi
  \fi
  \@tempskipa #5\relax
  \ifdim \@tempskipa>\z@
    \begingroup
    #6{%
       \@hangfrom{\hskip #3\relax\@svsec}%
         \interlinepenalty \@M #8\@@par}%
    \endgroup
    \csname #1mark\endcsname{#7}%
    \ifnum #2=\@ne
      \addcontentsline{toc}{#1}{%
        \ifnum #2>\c@secnumdepth \else
        \ifappendix \appendixname~\csname the#1\endcsname
        \else \protect\numberline{\csname the#1\endcsname.}#7\fi
        \fi}%
    \else
      \addcontentsline{toc}{#1}{%
        \ifnum #2>\c@secnumdepth \else
        \protect\numberline{\csname the#1\endcsname.}#7\fi}%
    \fi
  \else
    \def\@svsechd{%
      #6{\hskip #3\relax
      \@svsec #8}%
      \csname #1mark\endcsname{#7}%
      \addcontentsline{toc}{#1}{%
        \ifnum #2>\c@secnumdepth \else
          \protect\numberline{\csname the#1\endcsname.}%
        \fi
        #7}}%
  \fi
  \@xsect{#5}\@afterindentfalse\@afterheading}%%% 3-8-20

%%%%%%% 3-8-20 %%%%
\def\@ssect#1#2#3#4#5{%
  \@tempskipa #3\relax
  \ifdim \@tempskipa>\z@
    \begingroup
      #4{%
        \@hangfrom{\hskip #1}%
          \interlinepenalty \@M #5\@@par}%
    \endgroup
  \else
    \def\@svsechd{#4{\hskip #1\relax #5}}%
  \fi
  \@xsect{#3}\@afterindentfalse\@afterheading}
%%%%%%%%%%%%%%%%

\newif\ifappendix
\newif\ifoneappendix
\newcommand\appendixname{Appendix}

\newcommand\oneappendix{\global\oneappendixtrue \appendix}
\newcommand\appendix{\par
\setcounter{section}{0}
 % \setcounter{section}\z@
 \setcounter{equation}{0}
  %\setcounter{equation}\z@
  \renewcommand\thesection{\@Alph\c@section}%
  \renewcommand\thesubsection{\thesection.\@arabic\c@subsection}%
  \renewcommand\thesubsubsection{\thesubsection.\@arabic\c@subsubsection}%
  \renewcommand\theequation{\thesection\,\@arabic\c@equation}%
  \global\appendixtrue
}

\setcounter{secnumdepth}{3}

\newcounter{part}
\newcounter {section}
\newcounter {subsection}[section]
\newcounter {subsubsection}[subsection]
\newcounter {paragraph}[subsubsection]
\newcounter{refsection}[section]
\renewcommand\thepart          {\@arabic\c@part}
\renewcommand\thesection       {\@arabic\c@section}
\renewcommand\thesubsection    {\thesection.\@arabic\c@subsection}
\renewcommand\thesubsubsection {\thesubsection.\@arabic\c@subsubsection}
\renewcommand\theparagraph     {\thesubsubsection.\@arabic\c@paragraph}

\newlength\@indentskip
\newlength\smallindent
\newlength\@footindent
\newlength\@leftskip
\setlength\@indentskip{2.5em}
\setlength\smallindent{1em}
\setlength\@footindent{\smallindent}
\setlength\@leftskip{\z@}

\setlength\leftmargini{\z@}
\setlength\labelsep{\z@}
\setlength\labelwidth{\z@}

\newcommand\makeitemlabel[1]{\hspace\labelwidth\hspace\labelsep\hfill#1}

\def\@listI{\parsep\z@ \topsep\z@ \partopsep\z@ \itemsep\z@ \rightmargin\z@
  \leftmargin\labelwidth \advance\leftmargin\labelsep
  }

\def\@listi{\@listI \leftmargin\leftmargini \itemindent 1em}
\def\@listii{\@listI \advance\leftmargin .5em}
\def\@listiii{\@listI}
\def\@listiv{\@listI}
\def\@listv{\@listI}
\def\@listvi{\@listI}
\@listi

\def\itemize{% FROM LATEX.LTX
  \ifnum \@itemdepth >\thr@@ \@toodeep\else
    \advance\@itemdepth\@ne
    \edef\@itemitem{labelitem\romannumeral\the\@itemdepth}%
    \expandafter
    \list
      \csname\@itemitem\endcsname
      {\labelsep .5em\settowidth{\labelwidth}{\csname\@itemitem\endcsname}%
       \let\makelabel\makeitemlabel}%
  \fi
}

\newcommand\labelitemi{$\m@th\bullet$}
\newcommand\labelitemii{$\m@th\circ$}
\newcommand\labelitemiii{\normalfont\bfseries ---}
\newcommand\labelitemiv{\normalfont\bfseries --}

\def\enumerate{% FROM LATEX.LTX
  \ifnum \@enumdepth >\thr@@ \@toodeep\else
    \advance\@enumdepth\@ne
    \edef\@enumctr{enum\romannumeral\the\@enumdepth}%
  \fi
  \@ifnextchar [{\@enumeratetwo}{\@enumeratetwo[i]}%
}

\def\@enumeratetwo[#1]{%
  \expandafter
  \list
    \csname label\@enumctr\endcsname
    {\settowidth\labelwidth{#1}
    \labelwidth 1.5pc
    \labelsep .5em%
%     \advance\itemindent\labelsep
     \advance\itemindent\labelwidth
     \usecounter\@enumctr\relax}%
}

\newcommand\labelenumi  {{\normalfont\rmfamily(\theenumi)}}
\newcommand\labelenumii {{\normalfont\rmfamily(\theenumii)}}
\newcommand\labelenumiii{\theenumiii.}
\newcommand\labelenumiv {\theenumiv}

\renewcommand\theenumi{{\normalfont\@roman\c@enumi}}
\renewcommand\theenumii{{\normalfont\itshape\@alph\c@enumii}}
\renewcommand\theenumiii{\@roman\c@enumiii}
\renewcommand\theenumiv{\@roman\c@enumiv}

\renewcommand\p@enumii{\theenumi.}
\renewcommand\p@enumiii{\p@enumii\theenumii.}
\renewcommand\p@enumiv{\p@enumiii\theenumiii.}

\newcommand*\descriptionlabel[1]{\hspace\labelsep \normalfont\bfseries #1}

\newenvironment{description}
  {\list{}{\labelwidth\z@
  \ifnum\@listdepth=\@ne \else \advance\leftmargin 1em\fi
  \let\makelabel\descriptionlabel}}
  {\endlist}

\newenvironment{verse}
  {\let\\=\@centercr
   \list{}{\itemsep\z@
   \itemindent -\@indentskip
   \listparindent \itemindent
   \rightmargin\leftmargin
   \advance\leftmargin \@indentskip}\item[]}
  {\endlist}

\newenvironment{quotation}
  {\list{}{\listparindent\smallindent
   \itemindent\listparindent
   \leftmargin 1pc\rightmargin\leftmargin
   \topsep\halflineskip
   \parsep \z@ \@plus 1\p@}\item[]\qsmall\baselineskip 10.75\p@}
  {\endlist}

\newenvironment{quote}
  {\par\list{}{\leftmargin 1pc\rightmargin\leftmargin
   \listparindent\smallindent}\item[]%
   \qsmall\baselineskip 10.75\p@\rule{\z@}{10\p@}\ignorespaces}
  {\endlist}

\def\@begintheorem#1#2{% FROM LATEX.LTX
  \par\vskip\halflineskip {\normalfont\scshape #1\ #2.}%
  \enskip\normalfont\itshape}
\def\@opargbegintheorem#1#2#3{% FROM LATEX.LTX
  \par\vskip\halflineskip {\normalfont\scshape #1\ #2\ (#3).}%
  \enskip\normalfont\itshape}
\def\@endtheorem{\vskip\halflineskip\par}% FROM LATEX.LTX



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

% theorem* code from psp

\newif\ifrembrks
\newcommand\removebrackets{\rembrkstrue}

\def\@xnthm#1#2[#3]{% FROM LATEX.LTX
\expandafter\@ifdefinable\csname #1\endcsname
  {\@definecounter{#1}\@newctr{#1}[#3]%
   \expandafter\xdef\csname the#1\endcsname{\expandafter\noexpand
   \csname the#3\endcsname \@thmcountersep \@thmcounter{#1}}%
   \global\@namedef{#1}{\@thm{#1}{#2}}%
   \global\@namedef{#1*}{\@thmstar{#1}{#2}}%
   \global\@namedef{end#1}{\@endtheorem}%
   \global\@namedef{end#1*}{\@endthmstar}}%
}

\def\@ynthm#1#2{% FROM LATEX.LTX
\expandafter\@ifdefinable\csname #1\endcsname
  {\@definecounter{#1}%
   \expandafter\xdef\csname the#1\endcsname{\@thmcounter{#1}}%
   \global\@namedef{#1}{\@thm{#1}{#2}}%
   \global\@namedef{#1*}{\@thmstar{#1}{#2}}%
   \global\@namedef{end#1}{\@endtheorem}%
   \global\@namedef{end#1*}{\@endthmstar}}%
}

\def\@othm#1[#2]#3{% FROM LATEX.LTX
  \@ifundefined{c@#2}{\@nocounterr{#2}}%
    {\expandafter\@ifdefinable\csname #1\endcsname
    {\global\@namedef{the#1}{\@nameuse{the#2}}%
     \global\@namedef{#1}{\@thm{#2}{#3}}%
     \global\@namedef{#1*}{\@thmstar{#2}{#3}}%
     \global\@namedef{end#1}{\@endtheorem}%
     \global\@namedef{end#1*}{\@endthmstar}}}%
}

\def\@thmstar#1#2{\@ifnextchar[{\@ythmstar{#1}{#2}}{\@xthmstar{#1}{#2}}}
\def\@xthmstar#1#2{\@beginthmstar{#2}{\csname the#1\endcsname}\ignorespaces}
\def\@ythmstar#1#2[#3]{\@opargbeginthmstar{#2}{\csname the#1\endcsname}{#3}%
  \ignorespaces}

\def\@thmstarcounter#1{{}}
\def\@thmstarcountersep{{}}

\def\@beginthmstar#1#2{%
  \par\vskip\halflineskip {\normalfont\scshape #1.}%
  \enskip\normalfont\itshape}

\def\@opargbeginthmstar#1#2#3{%
  \par\vskip\halflineskip {\normalfont\scshape #1\ {\normalfont\rmfamily
  \ifrembrks #3\global\rembrksfalse\else (#3)\fi.}}%
  \normalfont\itshape\enskip}

\def\@endthmstar{\vskip\halflineskip\par}

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\newsavebox{\proofbox}
\sbox{\proofbox}{\unitlength 1\p@\begin{picture}(7,7)%
  \put(0,0){\framebox(7,7){}}\end{picture}}

\newlength\rpbdim
\newcommand\raiseproofboxby[1]{\setlength\rpbdim{#1}}
\def\raiseproofb@x{\llap{\vbox to\z@{\hsize=\wd\proofbox\vss
  \hbox{\usebox\proofbox}\vskip\rpbdim}}%
  \setlength\rpbdim{\z@}%
}

\newenvironment{proof}
  {\par\vskip\halflineskip {\normalfont\itshape Proof.}\enskip}
  {\hspace*{\fill}\ifdim\rpbdim=\z@ \usebox\proofbox\else \raiseproofb@x\fi
   \vskip\halflineskip\par}

\newenvironment{proof*}{\proof}{\vskip\halflineskip\par}

\newcommand\newremark[2]{%
  \newenvironment{#1}{\list{}{\topsep\halflineskip \labelwidth\z@
    \labelsep .5em \let\makelabel\makeitemlabel}%
  \item[{\normalfont\itshape #2.}]}{\endlist}%
}

\renewcommand\theequation{\thesection.\@arabic\c@equation}

% subeqn.sty follows
% Copyright (c) 1990 by Stephen Gildea
% Permission to copy all or part of this work is granted, provided
% that the copies are not made or distributed for resale, and that
% the copyright notice and this notice are retained.
% Modified for use with JFM/LaTeX2e.

\newif\ifuseAMSsubequ
\newcommand\useAMSsubequations{\global\useAMSsubequtrue}

\newtoks\@stequation

\newenvironment{CUPsubequations}
  {\refstepcounter{equation}%
   \edef\@savedequation{\the\c@equation}%
   \@stequation=\expandafter{\theequation}%
   \edef\@savedtheequation{\the\@stequation}%
   \edef\oldtheequation{\theequation}%
   \setcounter{equation}\z@
   \def\theequation{\oldtheequation{\itshape\alph{equation}}}}
  {\setcounter{equation}{\@savedequation}%
   \@stequation=\expandafter{\@savedtheequation}%
   \edef\theequation{\the\@stequation}\global\@ignoretrue}

\newcommand\returnthesubequation{%
  \gdef\thesubequation{\theequation{\itshape\@alph\c@subequation}}}

% subeqnarray.sty
% Copyright (C) 1988 by Johannes Braams, Dr Neher Laboratories
% Modified for use with JFM/LaTeX2e.

\newcounter{subequation}[equation]
\renewcommand\thesubequation{\theequation{\itshape\@alph\c@subequation}}
\def\@subeqnnum{{\normalfont\rmfamily (\thesubequation)}}

\newcommand\slabel[1]{\@bsphack % MODIFIED IN LINE WITH LATEX.LTX
  \protected@write\@auxout{}%
    {\string\newlabel{#1}{{\thesubequation}{\thepage}}}%
  \@esphack}

\newenvironment{subeqnarray} % MODIFIED IN LINE WITH LATEX.LTX
  {\stepcounter{equation}%
   \let\@currentlabel=\theequation
   \global\c@subequation\@ne
   \global\@eqnswtrue
   \m@th
   \global\@eqcnt\z@
   \tabskip\@centering
   \let\\\@subeqncr
   $$\everycr{}\halign to\displaywidth\bgroup
     \hskip\@centering$\displaystyle\tabskip\z@skip{##}$\@eqnsel
    &\global\@eqcnt\@ne \hfil${\;##\;}$\hfil
    &\global\@eqcnt\tw@
     $\displaystyle\tabskip\z@skip{##}$\hfil\tabskip\@centering
    &\hb@xt@\z@\bgroup\hss##\egroup
      \tabskip\z@skip \cr}
  {\@@subeqncr\egroup $$\global\@ignoretrue}

\def\@subeqncr{{\ifnum0=`}\fi\@ifstar{\global\@eqpen\@M
    \@ysubeqncr}{\global\@eqpen\interdisplaylinepenalty \@ysubeqncr}}

\def\@ysubeqncr{\@ifnextchar [{\@xsubeqncr}{\@xsubeqncr[\z@]}}


\def\@xsubeqncr[#1]{\ifnum0=`{\fi}\@@subeqncr
   \noalign{\penalty\@eqpen\vskip\jot\vskip #1\relax}}

\def\@@subeqncr{\let\@tempa\relax
    \ifcase\@eqcnt \def\@tempa{& & &}\or \def\@tempa{& &}
      \else \def\@tempa{&}\fi
     \@tempa \if@eqnsw\@subeqnnum\refstepcounter{subequation}\fi
     \global\@eqnswtrue\global\@eqcnt\z@\cr}

\let\@ssubeqncr=\@subeqncr
\newenvironment{subeqnarray*}
  {\def\@subeqncr{\nonumber\@ssubeqncr}\subeqnarray}
  {\global\advance\c@equation\m@ne \nonumber\endsubeqnarray}

\renewenvironment{eqnarray} % MODIFIED IN LINE WITH LATEX.LTX
  {\stepcounter{equation}%
   \let\@currentlabel=\theequation
   \global\@eqnswtrue
   \m@th
   \global\@eqcnt\z@
   \tabskip\@centering
   \let\\\@eqncr
   $$\everycr{}\halign to \displaywidth\bgroup
     \hskip\@centering$\displaystyle\tabskip\z@skip{##}$\@eqnsel
   &\global\@eqcnt\@ne \hfil${\;##\;}$\hfil
   &\global\@eqcnt\tw@
     $\displaystyle\tabskip\z@skip{##}$\hfil \tabskip\@centering
   &\hb@xt@\z@\bgroup\hss##\egroup
     \tabskip\z@skip \cr}
  {\@@eqncr\egroup\global\advance\c@equation\m@ne
   $$\global\@ignoretrue}

\newenvironment{titlepage}
  {\@restonecolfalse\if@twocolumn\@restonecoltrue\onecolumn
   \else \newpage \fi \thispagestyle{empty}\c@page\z@}
  {\if@restonecol\twocolumn \else \newpage \fi}

\setlength\arraycolsep{5\p@}
\setlength\tabcolsep{3\p@}
\setlength\arrayrulewidth{.5\p@}
\setlength\doublerulesep{1.5\p@}
\setlength\tabbingsep{\labelsep}
\setlength{\skip\@mpfootins}{5\p@ \@plus .4\p@ \@minus .4\p@}
\setlength\fboxsep{3\p@}
\setlength\fboxrule{.5\p@}

\newcommand\affiliation[1]{\gdef\@affiliation{\let\aff\aff@inst#1}}
\gdef\@affiliation{}

\newcommand\maketitle{\appendixfalse \iflineno\relax\nolinenumbers\fi%% 3-8-20
  \@ifnextchar [{\m@ketitleone}{\m@ketitletwo}}%
\def\m@ketitletwo{\m@ketitleone[n]}

\newif\iffofootnote
\newcommand\fulloutfootnote{\global\fofootnotetrue}

\def\m@ketitleone[#1]{\par\iflineno\relax\runninglinenumbers\fi% 3-8-20
  \begingroup \iflineno\relax\runninglinenumbers\fi%% 3-8-20
  \bgroup
    \def\@makefntext##1{%
      \iffofootnote
        \enskip\@thefnmark \ ##1\global\fofootnotefalse
      \else
        \setbox\@tempboxa\hbox{\quad\@thefnmark\enskip ##1}%
        \ifdim\wd\@tempboxa>\hsize \unhbox\@tempboxa\else
        \centerline{\unhbox\@tempboxa\quad}\fi
      \fi}%
    \newpage \global\@topnum\z@
    \@maketitle{#1}\thispagestyle{titlepage}\@thanks
  \egroup
  \endgroup
  \setcounter{footnote}\z@
  \global\let\@maketitle\relax
  \global\let\@thanks\@empty
  \global\let\@title\@empty
  \global\let\@author\@empty
  \global\let\@affiliation\@empty
  \global\let\maketitle\relax
  \global\let\thanks\relax
}

\renewcommand\and{{\normalfont
  \ifCUPmtlplainloaded
    \fontseries{sb}\fontshape{n}\fontsize{8}{12}\selectfont
  \else
    \indexsize\bfseries
  \fi
  and}%
}

\def\put@rapidsHead{\ifflm@rapids
 \noindent\minipage[t]{\linewidth}
 \vskip-25pt
 \hrule width \linewidth height 1.5pt
 \par\vskip 26pt
 \fontsize{30pt}{35pt}\sffamily\bfseries JFM RAPIDS\\
 \fontsize{12pt}{12pt}\sffamily\bfseries journals.cambridge.org/rapids\\[-3pt]
 \hrule width \linewidth height 1pt
 \endminipage\par\vskip 24pt\fi}

\def\put@absrule{\ifflm@rapids\par\vskip1pc\hrule\fi}

\def\@title@alignment{\ifflm@rapids\raggedright\fi}
\def\@author@alignment{\ifflm@rapids\raggedright\fi}
\def\@aff@alignment{\ifflm@rapids\raggedright\fi}
\def\@history@alignment{\ifflm@rapids\raggedright\fi}


\def\@maketitle#1{%
 \newpage
 \vspace*{10\p@}\addvspace{5pc}%
 {\flushleft
  {\normalfont\LARGE\fontswitch\bfseries
  \put@rapidsHead%
  \@title@alignment%
  \@title \par}%
  \vskip 14\p@ \@plus 2\p@ \@minus 1\p@
  {\normalfont\large\fontswitch\bfseries\baselineskip=12\p@
     \@author@alignment%
     \lowercase{\@author}\par}%
  \vskip 4\p@ \@plus 1\p@
  {\normalfont\small
  \@aff@alignment%
  \@affiliation \par}%
  \vskip 8\p@ \@plus 2\p@ \@minus 1\p@
  %{\normalfont\small (Received \@date)}% x@rem
  \normalfont\small
  \@history@alignment%
  (Received xx; revised xx; accepted xx)\hfill% x@add
  \put@absrule
 \par}%
 \vskip 8\p@ \@plus 2\p@ \@minus 1\p@
}

\newenvironment{abstract}
  {\par\normalfont\normalsize\noindent\ignorespaces}
  {\par\vskip 9\p@ \@plus 1\p@ \@minus 1\p@
%   \vbox{\centerline{\rule[4\p@]{30pc}{.4\p@}}}
}

\newenvironment{keywords}
  {\par\noindent{\bf Key words:}\ \normalfont\normalsize\noindent\ignorespaces}
  {\par\vskip 9\p@ \@plus 1\p@ \@minus 1\p@
   \ifflm@rapids\vskip-1pc\put@absrule\else%
   \vbox{\centerline{\rule[4\p@]{30pc}{.4\p@}}}
   \vskip 30pt
   \fi%
   }

\mark{{}{}}
\renewcommand\author{\@ifnextchar [{\@authortwo}{\@authorone}}
\def\@authortwo[#1]#2{\gdef\@author{#2}\gdef\@shortauthor{#1}}
\def\@authorone#1{\gdef\@author{\def\and{and }#1}%
 \begingroup\def\and{and}%\gdef\@shortauthor{#1}
 \endgroup}
\gdef\@author{\mbox{}}

\newcommand\shortauthor[1]{\edef\@tempx{#1}%
  \ifx\@tempx\@empty\gdef\@shortauthor{Short author list is empty!!}
  \else\gdef\@shortauthor{#1}\fi}
\gdef\@shortauthor{}

\renewcommand\title{\@ifnextchar [{\@titletwo}{\@titleone}}
\def\@titletwo[#1]#2{\gdef\@title{#2}\gdef\@shorttitle{#1}}
\def\@titleone#1{\gdef\@title{#1}%\gdef\@shorttitle{#1}
}
\gdef\@title{\mbox{}}

\newcommand\shorttitle[1]{\edef\@tempx{#1}%
 \ifx\@tempx\@empty\gdef\@shorttitle{Short title is empty!!}%
 \else\gdef\@shorttitle{#1}\fi}
\gdef\@shorttitle{}

\newcommand\volume[1]{\gdef\@volume{#1}}
\gdef\@volume{11}

\newcommand\pagerange[1]{\gdef\@pagerange{#1}}
\gdef\@pagerange{1--000}

\newcommand\pubyear[1]{\def\@pubyear{#1}}
\edef\@pubyear{\number\year}

\newcommand\journal[1]{\gdef\@journal{#1}}

\newcommand\doi[1]{\gdef\@doi{10.1017/#1}}
\gdef\@doi{10.1017/S000000000000000X}

\gdef\@journal{%
  \vbox to 5.5\p@{\noindent
    \parbox[t]{4.5in}{\normalfont\indexsize\baselineskip 9\p@
      {\itshape J.\ Fluid\ Mech.} (\@pubyear), {\itshape vol.} \@volume,
      {\itshape pp.} \@pagerange.\quad \copyright\ \@pubyear\ Cambridge University
        Press\\[2.5\p@]
      DOI: \@doi\quad {Printed in the United Kingdom}}%
  \vss}%
}
\gdef\@underjournal{%
  \vbox to 5.5\p@{\noindent
    \parbox[t]{4.5in}{\normalfont\indexsize{\itshape Under consideration
      for publication in J.\ Fluid\ Mech.}\\[2.5\p@]
      {\ \ }}%
  \vss}%
}

\def\footerflagdefns#1{\hbox to \hsize{\hfill\colorbox{mycol}{\color{white}\fontsize{14}{16}\bfseries\selectfont#1}\hfill}}%

\def\absfooterflag{\footerflagdefns{Abstract must not spill onto p.2}}%

\def\pagelimitfooter{\bgroup%
\ifnum\c@page=4\relax%
\footerflagdefns{Focus on Fluids articles must not exceed this page length}%
\else%
\ifnum\c@page=10\relax%
\footerflagdefns{Rapids articles must not exceed this page length}%
\fi\fi%
\egroup}%

\def\ps@headings{\let\@mkboth\markboth
  \def\@oddhead{\hfil{\itshape\@shorttitle}\hfil\llap{\thepage}}%
  \def\@evenhead{\rlap{\thepage}\hfil\itshape\@shortauthor\hfil}%
  \def\@oddfoot{}%
  \def\@evenfoot{\pagelimitfooter}%
  \def\sectionmark##1{\markboth{##1}{}}%
  \def\subsectionmark##1{\markright{##1}}%
}

\usepackage{color}
\definecolor{mycol}{cmyk}{0,1,0,0}

\def\flmspecialinstruction#1{#1}
\def\ps@spheadings{\let\@mkboth\markboth
  \def\@oddhead{\hfil{\itshape\@shorttitle}\hfil\llap{\thepage}}%
  \def\@evenhead{\rlap{\thepage}\hfil\itshape\@shortauthor\hfil}%
  \def\@oddfoot{\vbox{\vskip10pt\colorbox{mycol}{\textcolor{white}{\fontseries{b}\fontsize{14}{16}\selectfont \flmspecialinstruction}}}}%
  \def\@evenfoot{\vbox{\vskip10pt\colorbox{mycol}{\textcolor{white}{\fontseries{b}\fontsize{14}{16}\selectfont \flmspecialinstruction}}}}%
  \def\sectionmark##1{\markboth{##1}{}}%
  \def\subsectionmark##1{\markright{##1}}%
}

\def\ps@myheadings{\let\@mkboth\@gobbletwo
  \def\@oddhead{\hfil{\itshape\rightmark}\hfil\llap{\thepage}}%
  \def\@evenhead{\rlap{\thepage}\hfil\itshape\leftmark\hfil}%
  \def\@oddfoot{}%
  \def\@evenfoot{}%
  \def\sectionmark##1{}%
  \def\subsectionmark##1{}%
}

\ifCUPmtlplainloaded
  \def\@j@urnal{\@journal}
\else
  \def\@j@urnal{\@underjournal}
\fi

\def\ps@titlepage{\leftskip\z@\let\@mkboth\@gobbletwo\vfuzz=5\p@
  \def\@oddhead{\vbox{\vspace*{-1pc}\hbox to \textwidth{\@j@urnal \hfil\llap{\thepage}}\par\vskip4pt%
\hbox to \textwidth{{\fboxsep0pt\fbox{\parbox{\textwidth}{\par\vskip2.7pc\centerline{Banner appropriate to article type will appear here in typeset article}\par\vskip2.7pc}}}}
}}
  \def\@evenhead{\@j@urnal \hfil\llap{\thepage}}%
  \def\@oddfoot{\absfooterflag}%
  \def\@evenfoot{\absfooterflag}%
  \def\sectionmark##1{}%
  \def\subsectionmark##1{}%
}

\newcommand\@pnumwidth{1.55em}
\newcommand\@tocrmarg {2.55em}
\newcommand\@dotsep{4.5}
\setcounter{tocdepth}{2}

\def\@dottedtocline#1#2#3#4#5{% FROM LATEX.LTX
  \ifnum #1>\c@tocdepth \else
    \vskip \z@ \@plus.2\p@
    {\leftskip #2\relax \rightskip \@tocrmarg \parfillskip -\rightskip
     \parindent #2\relax\@afterindenttrue
     \interlinepenalty\@M
     \leavevmode
     \@tempdima #3\relax
     \advance\leftskip \@tempdima \null\hskip -\leftskip
     {#4}\nobreak
     \leaders\hbox{$\m@th
        \mkern \@dotsep mu\hbox{\phantom{.}}\mkern \@dotsep
        mu$}\hfill
     \nobreak
     \hb@xt@\@pnumwidth{\hfil\normalfont \normalcolor #5}%
     \par}%
  \fi}

\newcommand\contentsname{CONTENTS}

\newcommand\tableofcontents{%
  \@restonecolfalse
  \if@twocolumn\@restonecoltrue\onecolumn\fi
  \vskip 4\p@ \@plus .5\p@
  \centerline{\normalfont\scshape \contentsname}%
  \vskip 3\p@
  \@starttoc{toc}%
  \if@restonecol\twocolumn\fi \par\vspace{12\p@}%
}

\newcommand*\l@section[2]{%
  \ifnum \c@tocdepth >\z@
    \addpenalty{\@secpenalty}%
    \@tempdima 1.5em%
    \begingroup
      \parindent \z@ \rightskip \@pnumwidth
      \parfillskip -\@pnumwidth \normalfont\rmfamily \leavevmode
      \advance\leftskip\@tempdima \hskip -\leftskip
      {\normalfont\bfseries #1}\nobreak\hfil
      \nobreak\hb@xt@\@pnumwidth{\hss #2}\par
    \endgroup
  \fi
}

\newcommand*\l@subsection{\@dottedtocline{2}{2.5em}{2.3em}}
\newcommand*\l@subsubsection{\@dottedtocline{3}{3.8em}{3.2em}}

\newif\if@restonecol
\newcommand\indexname{Index}

\newenvironment{theindex}
  {\section*{\indexname}%
   \addcontentsline{toc}{section}{\indexname}%
   \normalfont\footnotesize \parindent\z@ \parskip\z@ \@plus .1\p@\relax
   \let\item\@idxitem}
  {\if@restonecol\onecolumn\else\clearpage\fi}

\newcommand\@idxitem{\par\hangindent 1em\relax}
\newcommand\subitem{\@idxitem\hspace*{1em}}
\newcommand\subsubitem{\subitem}
\newcommand\indexspace{\par\vskip\baselineskip \relax}

\renewcommand\footnoterule{\setcounter{footnote}\z@}
\newcommand\@makempfntext[1]{\strut\@thefnmark\enskip #1}

\newcommand\@makefntext[1]{%
  \setbox\@tempboxa\hbox{\quad\@thefnmark\enskip #1}%
  \ifdim\wd\@tempboxa>\hsize
    \unhbox\@tempboxa
  \else
    \centerline{\unhbox\@tempboxa}%
  \fi
}

\long\def\@mpfootnotetext#1{% FROM LATEX.LTX
  \global\setbox\@mpfootins\vbox{%
    \unvbox\@mpfootins
    \reset@font\footnotesize
    \hsize\columnwidth
    \@parboxrestore
    \protected@edef\@currentlabel
         {\csname p@mpfootnote\endcsname\@thefnmark}%
    \color@begingroup \centering
      \@makempfntext{%
        \rule\z@\footnotesep\ignorespaces#1\@finalstrut\strutbox}%
    \color@endgroup}%
}

\def\@fnsymbol#1{% MODIFIED IN LINE WITH LATEX.LTX
  \ensuremath{\ifcase#1\or \dag\or \ddag\or \P\or \|\or
    \dag\dag\or \ddag\ddag\or \P\P\or \|\| \else\@ctrerr\fi}%
}

\renewcommand\@makefnmark{\hbox{\@thefnmark}}
\renewcommand\thempfootnote{\hbox{$\@fnsymbol\c@mpfootnote$}}

\setcounter{topnumber}{3}
\renewcommand\topfraction{.9}
\setcounter{bottomnumber}{0}
\renewcommand\bottomfraction{.9}
\setcounter{totalnumber}{3}
\renewcommand\textfraction{.05}
\renewcommand\floatpagefraction{.9}
\setcounter{dbltopnumber}{3}
\renewcommand\dbltopfraction{.9}
\renewcommand\dblfloatpagefraction{.5}

\newif\ifrem@fullpt
\newcommand\removefullpoint{\global\rem@fullpttrue}

\newif\ifbot@fig
\newenvironment{bottomfigure}{\def\fps@figure{b}%
  \setcounter{bottomnumber}{1}%
  \global\bot@figtrue
  \@float{figure}\fstyle@figure}
  {\end@float}

\usepackage[hang,small,center]{caption}
\setlength{\captionmargin}{30pt}

%\long\def\@makecaption\normalfont%{%
 % \ifbot@fig \rule{\textwidth}{.25pt}\fi
%  \vskip 5\p@ \@plus .4\p@ \@minus .4\p@
 % \begingroup
   % \small\setbox\@tempboxa\hbox{{\normalfont\scshape
    % #1\ifrem@fullpt\else .\fi} #2}%
    %\ifdim \wd\@tempboxa >\tw@\hsize
     % \unhbox\@tempboxa\par
  %  \else
      %{\centering \unhbox\@tempboxa\par}%
    %\fi
 % \endgroup
  %\global\rem@fullptfalse
 % \global\bot@figfalse
%}

\newcounter{table}
\renewcommand\thetable{\@arabic\c@table}
\def\fps@table{tp}
\def\ftype@table{1}
\def\ext@table{lot}
\newcommand\tablename{Table}
\def\fnum@table{\tablename~\thetable}

\newif\iffollowon
\newif\ifrmrule

\newcommand\followon{\global\followontrue}
\newcommand\norule{\global\rmruletrue}

\newenvironment{table}
  {\@float{table}\fstyle@table
   \iffollowon \else \vspace*{9.5\p@}\fi
   \global\followonfalse
   \rule{\textwidth}{.5\p@}\vskip\floatsep\relax}
  {\ifrmrule \global\rmrulefalse \else \rule{\textwidth}{.5\p@}\fi
   \end@float}

\newenvironment{table*}{\@dblfloat{table}\fstyle@table}{\end@dblfloat}
\newenvironment{plaintable}{\@float{table}\fstyle@table}{\end@float}

\def\fstyle@table{\normalfont\small\rmfamily}
\def\fjust@table{\centering}
\def\fcapjust@table{\centering}
\def\fcapsize@table{\normalfont\small\scshape}
\def\fcapstyle@table{\normalfont\small\rmfamily}

\newcounter{figure}
\renewcommand\thefigure{\@arabic\c@figure}
\def\fps@figure{tp}
\def\ftype@figure{2}
\def\ext@figure{lof}
\newcommand\figurename{Figure}
\def\fnum@figure{\figurename~\thefigure}

\newenvironment{figure}{\@float{figure}\fstyle@figure}{\end@float}
\newenvironment{figure*}{\@dblfloat{figure}\fstyle@figure}{\end@dblfloat}

\def\fstyle@figure{\normalfont\small\rmfamily}
\def\fjust@figure{\centering}
\def\fcapjust@figure{\centering}
\def\fcapsize@figure{\normalfont\small\scshape}
\def\fcapstyle@figure{\normalfont\small\rmfamily}

\newcommand\smallls{\kern.12em\relax}
\newcommand\ls{\kern.15em\relax}
\newcommand\ns{\kern.5em\relax}

\renewcommand{\thefootnote}{\mbox{$\@fnsymbol\c@footnote$}}

\renewcommand\hline{%
  \noalign{\ifnum0=`}\fi \vskip 6\p@
  \hrule \@height \arrayrulewidth \vskip 6\p@
  \futurelet \@tempa\@xhline
}

\renewcommand\@xhline{%
  \ifx\@tempa\hline \vskip -12\p@ \vskip\doublerulesep\fi \ifnum0=`{\fi}%
}

\newenvironment{acknowledgments}
  {\par\vskip 10\p@ \@plus 1\p@ \@minus 1\p@}{\par}
\let\acknowledgements\acknowledgments
\let\endacknowledgements\endacknowledgments

\newcommand\today{}
\edef\today{\number\day\ \ifcase\month\or
  January\or February\or March\or April\or May\or June\or
  July\or August\or September\or October\or November\or December
 \fi \ \number\year}

\newif\if@altcite
\renewcommand\@biblabel[1]{}% FROM LATEX.LTX
\newcommand\newblock{\hskip .11em \@plus .33em \@minus .07em\relax}
\newcommand\bibls{\kern.065em\relax}

\newenvironment{thebibliography}[1]{%
  \par\vskip 20\p@ \@plus 1\p@ \@minus 1\p@
  \ifflm@rapids\section*{References}\else
  \centerline{\normalfont\small\scshape R\bibls E\bibls F\bibls E\bibls
             R\bibls E\bibls N\bibls C\bibls E\bibls S}\fi%
 \nobreak
 \vskip 4\p@ \@plus .5\p@ \@minus .5\p@
 \nobreak
 \list{}{\labelwidth\z@ \leftmargin 2.5em \itemindent -2.5em \itemsep 1\p@}%
 \normalfont\small\parindent\z@
 \parskip\z@ \@plus .1\p@\relax
 \sloppy\clubpenalty\z@ \widowpenalty\@M
 \sfcode`\.\@m\relax}
 {\endlist}


\let\JFMthebib\thebibliography
\let\JFMendthebib\endthebibliography

\DeclareRobustCommand\cite{% FROM LATEX.LTX
  \@ifnextchar [{\@tempswatrue\global\@altcitetrue\@citex}
    {\@tempswafalse\global\@altcitefalse\@citex[]}}

\def\@citex[#1]#2{% FROM LATEX.LTX
  \let\@citea\@empty
  \@cite{\@for\@citeb:=#2\do
    {\@citea\def\@citea{,\penalty\@m\ }%
     \edef\@citeb{\expandafter\@firstofone\@citeb}%
     \if@filesw\immediate\write\@auxout{\string\citation{\@citeb}}\fi
     \@ifundefined{b@\@citeb}{\mbox{\reset@font\bfseries ?}%
       \G@refundefinedtrue
       \@latex@warning
         {Citation `\@citeb' on page \thepage \space undefined}}%
       {{\csname b@\@citeb\endcsname}}}}{#1}}

\renewcommand\@cite[2]{% FROM LATEX.LTX
  {\if@altcite #2\else #1\fi}\global\@altcitefalse}

\newif\iffontfound
\newcommand\checkfont[1]{%
  \batchmode
  \font\test=#1\relax
  \errorstopmode
  \fontfoundfalse
  \ifx\test\nullfont \else \fontfoundtrue\fi
}

\pagestyle{headings}
\pagenumbering{arabic}
\frenchspacing
\ifCUPmtlplainloaded
  \setlength\oddsidemargin\z@
  \setlength\evensidemargin\z@
  \setlength\topmargin\z@
\fi
\if@referee
  \renewcommand\baselinestretch{2}\raggedbottom
\else
  \flushbottom
\fi

\if@index
  \newcommand\indextitlesize{\@setfontsize\indextitlesize\@xiipt{18}}

  \renewcommand\ls{\kern.10em\relax}%.15
  \renewcommand\ns{\kern.44em\relax}% .5

  \def\@maketitle#1{%
    \newpage
    \vspace*{8\p@}%
    {\centering \sloppy
      {\normalfont\indextitlesize\fontswitch\bfseries \@title \par}%
      \vskip 14\p@ \@plus 2\p@ \@minus 1\p@
        {\normalfont\large\fontswitch\bfseries\baselineskip=12\p@
%       By\ns \uppercase{\@author}
        \par}%
      \vskip 4\p@ \@plus 1\p@
        {\normalfont\small \@affiliation \par}%
      \vskip 8\p@ \@plus 2\p@ \@minus 1\p@
%       {\normalfont\small (Received \@date)}%
        \par}%
    \vspace*{-14\p@ \@plus 2\p@ \@minus 1\p@}
  }
  \renewcommand\journal[1]{\gdef\@journal{#1}}
  \gdef\@journal{%
    \vbox to 5.5\p@{\noindent
      \parbox[t]{4.5in}{\normalfont\indexsize\baselineskip 9\p@
        \textsc{Journal of Fluid Mechanics}\hfill\textsc{Volume 423\quad\date}\\%[2.5\p@]
        {}
    }\vss}%
  }

  \def\ps@titlepage{\leftskip\z@\let\@mkboth\@gobbletwo\vfuzz=5\p@
    \def\@oddhead{\small\textsc{J\ls o\ls u\ls r\ls n\ls a\ls l\ns
      o\ls f\ns
      F\ls l\ls u\ls i\ls d\ns
      M\ls e\ls c\ls h\ls a\ls n\ls i\ls c\ls s}%
      \hfill\textsc{V\ls o\ls l\ls u\ls m\ls e\ns \@volume\quad 25\ns N\ls o\ls v\ls e\ls m\ls b\ls e\ls r\ns 2000}}%
    \def\@evenhead{\@j@urnal}%
    \def\@oddfoot{}%
    \def\@evenfoot{}%
    \def\sectionmark##1{}%
    \def\subsectionmark##1{}%
  }

  \renewcommand*\descriptionlabel[1]{\hspace\labelsep \normalfont\fontswitch\bfseries #1}
  \renewenvironment{description}
    {\list{}{\parsep 4pt\small\labelwidth\z@\labelsep 0.5em
    \leftmargin 18pt\itemindent-\leftmargin
    \let\makelabel\descriptionlabel}}
    {\endlist}

  \renewcommand\title{\@ifnextchar [{\@titletwo}{\@titleone}}
  \def\@titletwo[#1]#2{\gdef\@title{#2}\gdef\@shorttitle{#1}}
  \def\@titleone#1{\gdef\@title{#1}\gdef\@shorttitle{#1}}
  \gdef\@title{\mbox{}}
\fi% end of \if@index


%% Extracted from old version of jfm-instructions.tex
% For units of measure
\newcommand\dynpercm{\nobreak\mbox{$\;$dyn\,cm$^{-1}$}}
\newcommand\cmpermin{\nobreak\mbox{$\;$cm\,min$^{-1}$}}

% Various bold symbols
\providecommand\bnabla{\boldsymbol{\nabla}}
\providecommand\bcdot{\boldsymbol{\cdot}}
\newcommand\biS{\boldsymbol{S}}
\newcommand\etb{\boldsymbol{\eta}}

% For multiletter symbols
\newcommand\Real{\mbox{Re}}          % cf plain TeX's \Re and Reynolds number
\newcommand\Imag{\mbox{Im}}           % cf plain TeX's \Im
\newcommand\Rey{\mbox{\textit{Re}}}  % Reynolds number
\newcommand\Pran{\mbox{\textit{Pr}}} % Prandtl number, cf TeX's \Pr product
\newcommand\Pen{\mbox{\textit{Pe}}}  % Peclet number
\newcommand\Ai{\mbox{Ai}}            % Airy function
\newcommand\Bi{\mbox{Bi}}            % Airy function

%Bessel function
\newcommand\rmJ{{\rm J}}
\newcommand\rmY{{\rm Y}}
\newcommand\rmK{{\rm K}}
\newcommand\rmI{{\rm I}}

\newcommand\ssC{\mathsf{C}}    % for sans serif C
\newcommand\sfsP{\mathsfi{P}}  % for sans serif sloping P
\newcommand\slsQ{\mathsfbi{Q}} % for sans serif bold-sloping Q

% Hat position
\newcommand\hatp{\skew3\hat{p}}      % p with hat
\newcommand\hatR{\skew3\hat{R}}      % R with hat
\newcommand\hatRR{\skew3\hat{\hatR}} % R with 2 hats
\newcommand\doubletildesigma{\skew2\tilde{\skew2\tilde{\Sigma}}}
%       italic Sigma with double tilde

% array strut to make delimiters come out right size both ends
\newsavebox{\astrutbox}
\sbox{\astrutbox}{\rule[-5pt]{0pt}{20pt}}
\newcommand{\astrut}{\usebox{\astrutbox}}

\newcommand\GaPQ{\ensuremath{G_a(P,Q)}}
\newcommand\GsPQ{\ensuremath{G_s(P,Q)}}
\newcommand\p{\ensuremath{\partial}}
\newcommand\tti{\ensuremath{\rightarrow\infty}}
\newcommand\kgd{\ensuremath{k\gamma d}}
\newcommand\shalf{\ensuremath{{\scriptstyle\frac{1}{2}}}}
\newcommand\sh{\ensuremath{^{\shalf}}}
\newcommand\smh{\ensuremath{^{-\shalf}}}
\newcommand\squart{\ensuremath{{\textstyle\frac{1}{4}}}}
\newcommand\thalf{\ensuremath{{\textstyle\frac{1}{2}}}}
\newcommand\Gat{\ensuremath{\widetilde{G_a}}}
\newcommand\ttz{\ensuremath{\rightarrow 0}}
\newcommand\ndq{\ensuremath{\frac{\mbox{$\partial$}}{\mbox{$\partial$} n_q}}}
\newcommand\sumjm{\ensuremath{\sum_{j=1}^{M}}}
\newcommand\pvi{\ensuremath{\int_0^{\infty}%
  \mskip \ifCUPmtlplainloaded -30mu\else -33mu\fi -\quad}}

\newcommand\etal{\mbox{\textit{et al.}}}
\newcommand\etc{etc.\ }
\newcommand\eg{e.g.\ }


% See if the author has the AMS 'amsbsy' package installed: If they have,
% use it to provide better bold math support (with \boldsymbol).

\ifCUPmtlplainloaded \else
  \IfFileExists{amsbsy.sty}
    {\typeout{^^JFound the 'amsbsy' package on the system, using it.^^J}%
     \usepackage{amsbsy}}
    {\providecommand\boldsymbol[1]{\mbox{\boldmath $##1$}}}
\fi

% See if the author has AMS Euler fonts installed: If they have, attempt
% to use the 'upmath' package to provide upright math.
\ifCUPmtlplainloaded \else
  \checkfont{eurm10}
  \iffontfound
    \IfFileExists{upmath.sty}
      {\typeout{^^JFound AMS Euler Roman fonts on the system,
                   using the 'upmath' package.^^J}%
       \usepackage{upmath}}
      {\typeout{^^JFound AMS Euler Roman fonts on the system, but you
                   dont seem to have the}%
       \typeout{'upmath' package installed. JFM.cls can take advantage
                 of these fonts,^^Jif you use 'upmath' package.^^J}%
       \providecommand\upi{\pi}%
      }
  \else
    \providecommand\upi{\pi}%
  \fi
\fi



% See if the author has AMS symbol fonts installed: If they have, attempt
% to use the 'amssymb' package to provide the AMS symbol characters.

\ifCUPmtlplainloaded \else
  \checkfont{msam10}
  \iffontfound
    \IfFileExists{amssymb.sty}
      {\typeout{^^JFound AMS Symbol fonts on the system, using the
                'amssymb' package.^^J}%
       \usepackage{amssymb}%
       \let\le=\leqslant  \let\leq=\leqslant
       \let\ge=\geqslant  \let\geq=\geqslant
      }{}
  \fi
\fi

% Extras

\hyphenpenalty 9500
\emergencystretch 20pt
\tolerance=300

\def\aff#1{\ignorespaces\textsuperscript{#1}}
\def\aff@inst#1{\par\vskip3pt\textsuperscript{#1}\unskip\ignorespaces}
\def\email#1{Email address for correspondence: #1}

\def\corresp#1{\unskip\thanks{#1}}
\def\aunote#1{\unskip\thanks{#1}}

% Figure caption legends:
\newcommand{\opensquare}{\mbox{$\square$}}
\newcommand{\opentriangle}{\mbox{$\vartriangle$}}
\newcommand{\opentriangledown}{\mbox{$\triangledown$}}
\newcommand{\opendiamond}{\mbox{$\lozenge$}}
\newcommand{\fullsquare}{\mbox{$\blacksquare$}}
\newcommand{\fulldiamond}{\mbox{$\blacklozenge$}}
\newcommand{\fullstar}{\mbox{$\bigstar$}}
\newcommand{\fulltriangle}{\mbox{$\blacktriangle$}}
\let\fulltri=\fulltriangle
\newcommand{\fulltriangledown}{\mbox{$\blacktriangledown$}}
\let\fulltridown=\fulltriangledown
\newcommand{\opencirc}{\mbox{\Large$\circ$}}
\newcommand{\opensqr}{\mbox{$\square$}}
\newcommand{\opentri}{\mbox{$\triangle$}}
\newcommand{\opentridown}{\mbox{$\bigtriangledown$}}
%\newcommand{\opendiamond}{\mbox{$\diamondsuit$}}
\newcommand{\fullcirc}{\mbox{{\Large$\bullet$}}}
\newcommand{\fullsqr}{\,\vrule height5pt depth0pt width5pt}
\newcommand{\dotted}{\protect\mbox{${\mathinner{\cdotp\cdotp\cdotp\cdotp\cdotp\cdotp}}$}}
\newcommand{\dashed}{\protect\mbox{-\ -\ -\ -}}
\newcommand{\broken}{\protect\mbox{-- -- --}}
\newcommand{\longbroken}{\protect\mbox{--- --- ---}}
\newcommand{\chain}{\protect\mbox{--- $\cdot$ ---}}
\newcommand{\dashddot}{\protect\mbox{--- $\cdot$ $\cdot$ ---}}
\newcommand{\full}{\protect\mbox{------}}

% For sans serif characters:
% The following macros are setup in JFM.cls for sans-serif fonts in text
% and math.  If you use these macros in your article, the required fonts
% will be substitued when your article is typeset by the typesetter.
%
% \textsfi, \mathsfi   : sans-serif slanted
% \textsfb, \mathsfb   : sans-serif bold
% \textsfbi, \mathsfbi : sans-serif bold slanted (doesnt exist in CM fonts)
%
% For san-serif roman use \textsf and \mathsf as normal.
\iflineno\AtBeginDocument{\usepackage{lineno-FLM}}\fi% 3-8-20
% Greek letters
\let\rmGamma  \Gamma
\let\rmDelta  \Delta
\let\rmTheta  \Theta
\let\rmLambda \Lambda
\let\rmXi     \Xi
\let\rmPi     \Pi
\let\rmSigma  \Sigma
\let\rmUpsilon\Upsilon
\let\rmPhi    \Phi
\let\rmPsi    \Psi
\let\rmOmega  \Omega

\def\Gamma  {\varGamma}
\def\Delta  {\varDelta}
\def\Theta  {\varTheta}
\def\Lambda {\varLambda}
\def\Xi     {\varXi}
\def\Pi     {\varPi}
\def\Sigma  {\varSigma}
\def\Upsilon{\varUpsilon}
\def\Phi    {\varPhi}
\def\Psi    {\varPsi}
\def\Omega  {\varOmega}

\let\mathbi\boldsymbol

%%%%%% 8-8-20 %% Introduced for back section with small font size
\newcounter{savesecnumdepth}
\providecommand{\backsectionname}{Acknowledgements}
\newcommand{\backsection}[2][\backsectionname]{\begingroup\par%
  \small%
  \setcounter{savesecnumdepth}{\value{secnumdepth}}%
  \setcounter{secnumdepth}{0}%
\vskip6pt
\noindent \textbf{#1.} #2\par%
  \setcounter{secnumdepth}{\value{savesecnumdepth}}%
  \endgroup}
%%%%%%

\endinput

%%% Date: 3-8-20
%%% Updated the template to get the line numbers using lineno.sty
%%% Inserted \@afterindentfalse\@afterheading to avoid indentation after headings

%%% Date 8-8-20
%%% Changed the default point size as 10.5 for FLM new style \edef\t@xtsize{\ifCUPmtlplainloaded 10.5\else 10\fi}
%%% Introduced \backsection tag to make the heading run on style with small font size as like references.

% end of file jfm.cls
